import os
import streamlit as st
from volcenginesdkarkruntime import Ark

# ===================== API基础配置（与你官方调用格式完全一致） =====================
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_NAME = "doubao-seed-2-1-turbo-260628"


def get_ark_client():
    """初始化Ark客户端，从系统环境变量读取密钥，避免硬编码泄露"""
    # api_key = os.environ.get("ARK_API_KEY")

    # 云端优先读取后台Secrets
    if "ARK_API_KEY" in st.secrets:
        api_key = st.secrets["ARK_API_KEY"]
    else:
        # 本地电脑兼容系统环境变量
        api_key = os.environ.get("ARK_API_KEY")


    if not api_key:
        raise ValueError("未检测到环境变量 ARK_API_KEY，请先在系统环境变量中配置后再使用")
    client = Ark(
        base_url=BASE_URL,
        api_key=api_key
    )
    return client


# ===================== 核心功能：生成资产质量分析报告 =====================
def generate_risk_report(analysis_result):
    """
    输入：run_full_analysis() 返回的风控分析结果字典
    输出：AI生成的专业资产质量分析报告文本
    """
    try:
        # ========== 1. 基础数据提取 ==========
        roll_rate = analysis_result["roll_rate"]
        monthly_balance = analysis_result["monthly_balance"]
        provision = analysis_result["monthly_provision"]
        vintage_pivot = analysis_result["vintage_pivot"]
        analysis_date = analysis_result["analysis_date"].strftime("%Y年%m月%d日")
        # 容错读取逾期阈值
        overdue_threshold = analysis_result.get("overdue_threshold", 16)

        # ========== 2. 迁徙率维度 ==========
        month_cols = [col for col in roll_rate.columns if col != "近12月平均值"]
        latest_month = month_cols[-1]
        recent_6_months = month_cols[-6:]
        roll_avg = roll_rate["近12月平均值"].round(4)
        roll_recent_6 = roll_rate[recent_6_months].round(4)

        # ========== 3. 资产结构维度 ==========
        balance_latest = monthly_balance[latest_month]
        total_balance = balance_latest["合计"]

        # 修正M3+口径：包含M3~M7全档位
        m3_plus_labels = [
            "M3(61-90天)", "M4(91-120天)", "M5(121-150天)",
            "M6(151-180天)", "M7(181天+)"
        ]
        m3_plus_labels = [x for x in m3_plus_labels if x in balance_latest.index]
        m3_plus_balance = balance_latest.loc[m3_plus_labels].sum()
        m3_plus_rate = m3_plus_balance / total_balance if total_balance != 0 else 0

        balance_share = (balance_latest / total_balance).round(4)
        latest_prov = provision.iloc[-1]
        provision_rate = latest_prov["应计提拨备率"]

        # ========== 核心：所有指标预格式化 ==========
        fmt = {
            "总资产余额_亿元": f"{total_balance / 100000000:.2f}",
            "当月拨备_万元": f"{latest_prov['当月应计提拨备'] / 10000:.2f}",
            "M3+不良余额_万元": f"{m3_plus_balance / 10000:.2f}",
            "整体拨备率": f"{provision_rate * 100:.2f}%",
            "M3+不良率": f"{m3_plus_rate * 100:.2f}%",
            "M0占比": f"{balance_share.get('M0(正常)', 0) * 100:.2f}%",
            "M1占比": f"{balance_share.get('M1(1-30天)', 0) * 100:.2f}%",
            "M2占比": f"{balance_share.get('M2(31-60天)', 0) * 100:.2f}%",
            "关注类合计占比": f"{(balance_share.get('M1(1-30天)', 0) + balance_share.get('M2(31-60天)', 0)) * 100:.2f}%",
            "M7损失类占比": f"{balance_share.get('M7(181天+)', 0) * 100:.2f}%",
        }

        # ========== 4. Vintage维度 ==========
        all_batches = vintage_pivot.index.tolist()
        all_mobs = vintage_pivot.columns.tolist()

        latest_batch = all_batches[-1]
        latest_row = vintage_pivot.loc[latest_batch]
        valid_mobs_latest = [mob for mob in all_mobs if latest_row[mob] != '-']
        target_mob = max(valid_mobs_latest) if valid_mobs_latest else 1

        same_mob_comparison = []
        for batch in all_batches:
            val = vintage_pivot.loc[batch, target_mob]
            if val != '-':
                same_mob_comparison.append((batch, float(val)))
        recent_12_same_mob = same_mob_comparison[-12:]

        latest_year, latest_month_str = latest_batch.split('-')
        last_year_batch = f"{int(latest_year)-1}-{latest_month_str}"
        yoy_rate = None
        if last_year_batch in vintage_pivot.index:
            yoy_val = vintage_pivot.loc[last_year_batch, target_mob]
            if yoy_val != '-':
                yoy_rate = float(yoy_val)

        mature_batches = []
        for batch in all_batches[:-12]:
            row = vintage_pivot.loc[batch]
            valid_values = [float(x) for x in row if x != '-']
            if len(valid_values) >= 24:
                peak_rate = max(valid_values)
                mature_batches.append((batch, peak_rate))
        avg_mature_peak = sum([x[1] for x in mature_batches]) / len(mature_batches) if mature_batches else 0

        recent_batch_num = 6
        recent_batches = all_batches[-recent_batch_num:]
        batch_evolution = []
        for batch in recent_batches:
            row = vintage_pivot.loc[batch]
            valid_points = []
            for mob in all_mobs:
                val = row[mob]
                if val != '-':
                    valid_points.append((int(mob), float(val)))
            valid_points.sort(key=lambda x: x[0])
            batch_evolution.append((batch, valid_points))

        # ========== 5. 风险预警与集中度指标（修正缩进：放在循环外） ==========
        continuous_df = analysis_result["continuous_deterioration"]
        deteriorate_count = len(continuous_df)
        deteriorate_amount = continuous_df["未偿还本金"].sum() if deteriorate_count > 0 else 0
        avg_deteriorate_periods = continuous_df["连续升档期数"].mean() if deteriorate_count > 0 else 0

        first_ovd_df = analysis_result["first_overdue"]
        first_ovd_count = len(first_ovd_df)
        total_contracts = analysis_result["df_clean"]["合同号"].nunique()
        first_ovd_rate = first_ovd_count / total_contracts if total_contracts > 0 else 0
        avg_first_dpd = first_ovd_df["逾期天数（DPD）"].mean() if first_ovd_count > 0 else 0

        prov_df = analysis_result["monthly_provision"]
        prov_latest_val = prov_df.iloc[-1]["当月应计提拨备"]
        prov_prev_val = prov_df.iloc[-2]["当月应计提拨备"] if len(prov_df) >= 2 else prov_latest_val
        prov_change_rate = (prov_latest_val - prov_prev_val) / prov_prev_val if prov_prev_val != 0 else 0

        fmt_warn = {
            "持续恶化户数": f"{deteriorate_count}户",
            "持续恶化本金_万元": f"{deteriorate_amount / 10000:.2f}万元",
            "平均恶化期数": f"{avg_deteriorate_periods:.1f}期",
            "首逾期户数": f"{first_ovd_count}户",
            "首逾期率": f"{first_ovd_rate * 100:.2f}%",
            "平均首逾天数": f"{avg_first_dpd:.1f}天",
            "当月拨备环比": f"{prov_change_rate * 100:+.2f}%",
        }

        # ========== 6. 拼接完整 data_summary ==========
        data_summary = f"""
【一、分析基础信息】
分析基准日：{analysis_date}
逾期判定：DPD≥{overdue_threshold}天记为逾期，M7回收率假设30%

统计规则说明（AI解读必须严格遵守，不得违反）：
1. M5-M6、M6-M7档位因尾部余额基数通常极小，迁徙率数值波动大且可能超过100%，属于统计基数效应，不作为核心风险判断依据，仅作参考
2. Vintage分析遵循同账龄对齐原则，仅相同MOB期数的数据可横向对比
3. 商用车融资租赁业务普遍规律：首期逾期率与批次最终峰值损失率呈强正相关，可用于辅助预判新批次长期风险

【二、资产总览与风险结构（{latest_month}）】
✅ 以下数值为最终展示值，必须原文摘抄，禁止任何计算、单位转换、修改精度：
- 月末在贷总资产余额：{fmt['总资产余额_亿元']}亿元
- 当月应计提拨备金额：{fmt['当月拨备_万元']}万元
- 当月拨备环比变动：{fmt_warn['当月拨备环比']}
- 整体拨备率：{fmt['整体拨备率']}
- M3+不良率：{fmt['M3+不良率']}
- 关注类（M1-M2）合计占比：{fmt['关注类合计占比']}
- 正常类（M0）余额占比：{fmt['M0占比']}
- 损失类（M7）占比：{fmt['M7损失类占比']}

各逾期等级余额占比明细：
"""
        for label in balance_share.index[:-1]:
            share_str = f"{balance_share[label] * 100:.2f}%"
            data_summary += f"  · {label}：{share_str}\n"

        data_summary += f"""
【三、迁徙率趋势分析】
✅ 以下比率均为最终百分比，必须原文摘抄，禁止二次计算
1. 近12月平均迁徙率：
"""
        for k, v in roll_avg.items():
            # 跳过非迁徙率项：M7假设回收率不放进列表
            if k == "M7假设回收率":
                continue
            # 尾部档位加*标注，和表格风格统一
            display_name = k
            if k in ["M5-M6", "M6-M7"]:
                display_name = f"{k}*"
            data_summary += f"  · {display_name}：{v * 100:.2f}%\n"

        data_summary += f"\n2. 近6个月逐月迁徙率（按时间从早到晚排列）：\n"
        # 过滤掉非迁徙率项，只保留真实档位
        core_roll_rows = [idx for idx in roll_recent_6.index if idx != "M7假设回收率"]
        header = "  档位 | " + " | ".join(recent_6_months)
        data_summary += header + "\n"
        data_summary += "  " + "-" * len(header.strip()) + "\n"
        for idx in core_roll_rows:
            # 修改点3：尾部档位加*标注
            display_name = idx
            if idx in ["M5-M6", "M6-M7"]:
                display_name = f"{idx}*"

            row_str = "  " + display_name + " | "
            row_str += " | ".join([f"{roll_recent_6.loc[idx, m] * 100:.2f}%" for m in recent_6_months])
            data_summary += row_str + "\n"

        # 表格底部补充注释 + 单独说明回收率假设
        data_summary += "\n注：带*档位因尾部余额基数极小，迁徙率波动剧烈，属于统计基数效应，不作为核心风险判断依据，仅作参考。\n"
        data_summary += "拨备口径补充：M7档位采用固定回收率假设 30%，用于损失率测算与拨备计提。\n"

        data_summary += f"""
【四、Vintage账龄表现】
统计规则补充：
- 同账龄对齐原则：仅相同MOB期数的逾期率可跨批次横向对比
- 单批次纵向数据：反映该批次资产风险随账龄的演化轨迹
- 成熟批次峰值：为资产充分演化后的最终损失参考，新批次账龄不足不直接对比

1. 统一对标基准：以最新批次【{latest_batch}】的最大有效账龄 MOB{target_mob} 为时点
   近12个批次同MOB逾期率（从早到晚，全部为最终百分比，禁止修改）：
"""
        for batch, rate in recent_12_same_mob:
            data_summary += f"  · {batch}：{rate * 100:.2f}%\n"

        if yoy_rate is not None:
            latest_rate = float(same_mob_comparison[-1][1])
            yoy_diff = latest_rate - yoy_rate
            data_summary += f"\n2. 同比对标（{latest_batch} vs {last_year_batch}，均为MOB{target_mob}）：\n"
            data_summary += f"  · 去年同期：{yoy_rate * 100:.2f}%\n"
            data_summary += f"  · 本期：{latest_rate * 100:.2f}%\n"
            data_summary += f"  · 同比差值：{yoy_diff * 100:+.2f}个百分点\n"

        data_summary += f"\n3. 近{recent_batch_num}个批次逐期演化明细（按放款时间从新到旧）：\n"
        for batch, points in reversed(batch_evolution):
            point_str = "，".join([f"MOB{mob}：{rate * 100:.2f}%" for mob, rate in points])
            data_summary += f"  · {batch}批次：{point_str}\n"

        if avg_mature_peak > 0:
            data_summary += f"\n4. 成熟批次长期损失参考（演化≥24期的批次峰值均值）：\n"
            data_summary += f"  · 历史平均峰值逾期率：{avg_mature_peak * 100:.2f}%\n"

        data_summary += f"""
【五、风险预警与集中度特征】
以下为最终展示值，必须原文摘抄：
1. 持续恶化高风险账户（判定规则：连续≥2期逾期等级逐期上升，无还款回落）
  · 持续恶化高风险账户数：{fmt_warn['持续恶化户数']}
  · 涉及未偿还本金：{fmt_warn['持续恶化本金_万元']}
  · 平均连续恶化期数：{fmt_warn['平均恶化期数']}

2. 首次逾期特征（合同户数口径）
  · 本期首逾期合同数：{fmt_warn['首逾期户数']}
  · 整体首逾期率：{fmt_warn['首逾期率']}
  · 平均首次逾期天数：{fmt_warn['平均首逾天数']}

3. 分析提示
  · 重点关注持续恶化账户的还款能力变化，防范风险进一步向下迁移
  · 首逾期表现为前端准入质量的核心观测指标，需持续跟踪新批次走势
"""

        user_prompt = data_summary.strip()

        # ========== 7. 系统提示词（强制格式+禁止规则） ==========
        system_prompt = """
你是资深融资租赁风控专家，擅长商用车融资租赁业务的资产质量分析。
请基于用户提供的业务数据，撰写一份专业、严谨的月度资产质量分析报告。

【绝对禁止规则，违反视为严重错误】
1. 禁止对任何金额、比率数值进行二次计算、单位换算、修改小数点精度
2. 所有数据必须100%原文摘抄用户提供的最终展示值，不得自行推演、估算、补充
3. 禁止编造数据、补充未给出的指标；不得自行臆测数据矛盾、质疑统计口径
4. 不得违反统计规则说明，不得对尾部档位迁徙率过度解读，不得违反同账龄对比原则

【输出格式强制要求】
1. 全文固定分为四个部分，每个部分以「一、资产质量整体概览」「二、迁徙率趋势与风险传导分析」「三、Vintage账龄表现解读」「四、风控管理优化建议」作为一级标题，标题单独占一行
2. 每个一级标题下的内容分段表述，逻辑分层清晰，禁止整段连排无换行
3. 每个大部分之间空一行，提升可读性
4. 风控建议部分必须分「贷前、贷中、贷后」三个维度展开，每个维度下可分点表述，必须对应前面识别的具体风险点
5. 语言为正式书面报告风格，避免口语化表达，全文控制在900-1100字
6. 输入中的「风险预警与集中度特征」数据，需对应融入资产概览、风险传导分析和风控建议章节，输出仍保持四大段结构，不得新增独立一级标题

【写作要求】
1. 所有结论必须基于提供的数据得出，不得凭空臆造；数据异常点需明确指出并结合业务逻辑解释
2. 风控建议必须针对性对应前文发现的风险特征，禁止空泛套话，要可落地
3. 优先突出核心风险变化和边际改善，主次分明
        """.strip()

        # ========== 8. 调用豆包API ==========
        client = get_ark_client()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=1200
        )

        report_content = response.choices[0].message.content.strip()

        # ========== 9. 兜底校验 ==========
        if fmt['总资产余额_亿元'] not in report_content:
            report_content = "⚠️ 【数据校验提示】报告核心余额数值可能存在偏差，请人工核对\n\n" + report_content

        return report_content

    except Exception as e:
        return f"⚠️ AI报告生成失败：{type(e).__name__} - {str(e)[:150]}"
