import os
import streamlit as st
from volcenginesdkarkruntime import Ark

# ===================== API基础配置 =====================
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_NAME = "doubao-seed-2-1-turbo-260628"


def get_ark_client():
    """初始化Ark客户端，云端+本地双兼容"""
    # 云端优先读取后台Secrets
    api_key = None
    # 先尝试读取streamlit云端密钥
    try:
        api_key = st.secrets["ARK_API_KEY"]
    except (KeyError, FileNotFoundError):
        # 本地环境读不到secrets，降级读取系统环境变量
        api_key = os.environ.get("ARK_API_KEY")

    if not api_key:
        raise ValueError("未检测到环境变量 ARK_API_KEY，请先在系统环境变量中配置后再使用")
    client = Ark(
        base_url=BASE_URL,
        api_key=api_key
    )
    return client

def build_analysis_prompts(analysis_result):
    """
    仅生成系统提示词和用户提示词，不调用API
    返回：(system_prompt, user_prompt)
    """
    # ========== 1. 基础数据提取 ==========
    roll_rate = analysis_result["roll_rate"]
    monthly_balance = analysis_result["monthly_balance"]
    provision = analysis_result["monthly_provision"]
    vintage_pivot = analysis_result["vintage_pivot"]
    analysis_date = analysis_result["analysis_date"].strftime("%Y年%m月%d日")
    overdue_threshold = analysis_result.get("overdue_threshold", 16)
    m7_recovery_rate = analysis_result.get("m7_recovery_rate", 0.3)
    m7_recovery_fmt = f"{m7_recovery_rate * 100:.2f}%"

    # ========== 2. 迁徙率维度 ==========
    month_cols = [col for col in roll_rate.columns if col != "近12月平均值"]
    latest_month = month_cols[-1]
    recent_6_months = month_cols[-6:]
    roll_avg = roll_rate["近12月平均值"].round(4)
    roll_recent_6 = roll_rate[recent_6_months].round(4)

    # ========== 3. 资产结构维度 ==========
    balance_latest = monthly_balance[latest_month]
    total_balance = balance_latest["合计"]

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

    # ---------- 原逻辑：最新批次（保留用于其他模块） ----------
    latest_batch = all_batches[-1]
    latest_row = vintage_pivot.loc[latest_batch]
    valid_mobs_latest = [mob for mob in all_mobs if latest_row[mob] != '-']
    target_mob = max(valid_mobs_latest) if valid_mobs_latest else 1

    # ---------- 补回：历史各MOB期平均基准线 ----------
    mob_benchmark = {}
    for mob in all_mobs:
        valid_values = []
        for batch in all_batches:
            val = vintage_pivot.loc[batch, mob]
            if val != '-':
                valid_values.append(float(val))
        # 至少3个批次有数据，才作为有效基准，避免偶然偏差
        if len(valid_values) >= 3:
            mob_benchmark[int(mob)] = sum(valid_values) / len(valid_values)
    # 按MOB期号升序排列
    mob_benchmark = dict(sorted(mob_benchmark.items()))

    # ---------- 新增：选择同比对标批次（有≥3期有效账龄的最新批次） ----------
    yoy_batch = latest_batch
    yoy_row = latest_row
    # 倒序遍历，找第一个有效账龄≥3的批次
    for batch in reversed(all_batches):
        row = vintage_pivot.loc[batch]
        valid_mobs = [mob for mob in all_mobs if row[mob] != '-']
        if len(valid_mobs) >= 3:
            yoy_batch = batch
            yoy_row = row
            break

    # ---------- 同比多期对标（找共同所有有效MOB） ----------
    latest_year, latest_month_str = yoy_batch.split('-')
    last_year_batch = f"{int(latest_year) - 1}-{latest_month_str}"
    yoy_comparison = []
    if last_year_batch in vintage_pivot.index:
        last_year_row = vintage_pivot.loc[last_year_batch]
        for mob in all_mobs:
            ly_val = last_year_row[mob]
            lt_val = yoy_row[mob]
            if ly_val != '-' and lt_val != '-':
                yoy_comparison.append((int(mob), float(ly_val), float(lt_val)))
        yoy_comparison.sort(key=lambda x: x[0])

    # ---------- 成熟批次长期损失参考 ----------
    mature_batches = []
    for batch in all_batches[:-12]:
        row = vintage_pivot.loc[batch]
        valid_values = [float(x) for x in row if x != '-']
        if len(valid_values) >= 24:
            peak_rate = max(valid_values)
            mature_batches.append((batch, peak_rate))
    avg_mature_peak = sum([x[1] for x in mature_batches]) / len(mature_batches) if mature_batches else 0

    # ---------- 批次演化从6期扩至12期 ----------
    recent_batch_num = 12
    recent_batches = all_batches[-(recent_batch_num + 1) : -1]
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

    # ========== 5. 风险预警与集中度指标 ==========
    continuous_df = analysis_result["continuous_deterioration"]
    deteriorate_count = len(continuous_df)
    deteriorate_amount = continuous_df["未偿还本金"].sum() if deteriorate_count > 0 else 0
    avg_deteriorate_periods = continuous_df["连续升档期数"].mean() if deteriorate_count > 0 else 0

    first_ovd_df = analysis_result["first_overdue"]
    first_ovd_count = len(first_ovd_df)
    total_contracts = analysis_result["df_clean"]["合同号"].nunique()
    first_ovd_rate = first_ovd_count / total_contracts if total_contracts > 0 else 0
    avg_first_dpd = first_ovd_df["逾期天数（DPD）"].mean() if first_ovd_count > 0 else 0
    avg_first_period = first_ovd_df["期号"].mean() if first_ovd_count > 0 else 0
    # 新增：计算在贷资产平均合同期限（作为风险阶段参照基准）
    all_contracts = analysis_result["df_clean"].drop_duplicates(subset=["合同号"])
    # 字段名请和你实际数据列名对齐，常见名：合同总期数 / 总期数 / 合同期限
    if "期限" in all_contracts.columns:
        avg_contract_term = all_contracts["期限"].mean()
    else:
        avg_contract_term = 30.0        # 字段不存在时的兜底默认值

    # 应计拨备及环比
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
        "平均首逾期期数": f"{avg_first_period:.1f}期",  # 新增字段
        "平均合同期限": f"{avg_contract_term:.1f}期",  # 新增
        "当月拨备环比": f"{prov_change_rate * 100:+.2f}%",
    }

    # ========== 6. 拼接完整 data_summary ==========
    data_summary = f"""
【一、分析基础信息】
分析基准日：{analysis_date}
逾期判定：DPD≥{overdue_threshold}天记为逾期，M7回收率假设{m7_recovery_fmt}

统计规则说明（AI解读必须严格遵守，不得违反）：
1. M5-M6、M6-M7档位因尾部余额基数通常极小，迁徙率数值波动大且可能超过100%，属于统计基数效应，不作为核心风险判断依据，仅作参考
2. Vintage分析遵循同账龄对齐原则，仅相同MOB期数的数据可横向对比
3. 融资租赁业务普遍规律：首期逾期率与批次最终峰值损失率呈强正相关，可用于辅助预判新批次长期风险

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
        if k == "M7假设回收率":
            continue
        display_name = k
        if k in ["M5-M6", "M6-M7"]:
            display_name = f"{k}*"
        data_summary += f"  · {display_name}：{v * 100:.2f}%\n"

    data_summary += f"\n2. 近6个月逐月迁徙率（按时间从早到晚排列）：\n"
    core_roll_rows = [idx for idx in roll_recent_6.index if idx != "M7假设回收率"]
    header = "  档位 | " + " | ".join(recent_6_months)
    data_summary += header + "\n"
    data_summary += "  " + "-" * len(header.strip()) + "\n"
    for idx in core_roll_rows:
        display_name = idx
        if idx in ["M5-M6", "M6-M7"]:
            display_name = f"{idx}*"
        row_str = "  " + display_name + " | "
        row_str += " | ".join([f"{roll_recent_6.loc[idx, m] * 100:.2f}%" for m in recent_6_months])
        data_summary += row_str + "\n"

    data_summary += "\n注：带*档位因尾部余额基数极小，迁徙率波动剧烈，属于统计基数效应，不作为核心风险判断依据，仅作参考。\n"
    data_summary += f"拨备口径补充：M7档位假设固定回收率为 {m7_recovery_fmt}，用于损失率测算与拨备计提。\n"

    data_summary += f"""
【四、Vintage账龄表现】
统计规则补充：
- 同账龄对齐原则：仅相同MOB期数的逾期率可跨批次横向对比
- 历史基准线：所有历史有效批次同账龄逾期率的算术平均值，用于判断当前批次资产质量相对优劣
- 成熟批次峰值：资产充分演化后的最终损失参考，新批次账龄不足不直接对比

1. 历史各MOB期平均基准线（所有历史批次均值，用于对标参考）
"""
    # 输出历史基准
    if mob_benchmark:
        for mob, rate in mob_benchmark.items():
            if mob <= 12:  # 仅新增这一行判断，限制输出到MOB12
                data_summary += f"  · MOB{mob}：{rate * 100:.2f}%\n"
    else:
        data_summary += "  · 历史批次样本不足，暂不生成基准线\n"

    data_summary += f"\n2. 近{recent_batch_num}个完整表现批次（不含当月新投放，按放款时间从新到旧）：\n"
    for batch, points in reversed(batch_evolution):
        point_str = "，".join([f"MOB{mob}：{rate * 100:.2f}%" for mob, rate in points])
        data_summary += f"  · {batch}批次：{point_str}\n"

    # 同比多期对标
    if yoy_comparison and len(yoy_comparison) >= 2:
        data_summary += f"\n3. 同比对标（{yoy_batch} vs {last_year_batch}，同账龄逐期对比）：\n"
        for mob, ly_rate, lt_rate in yoy_comparison:
            diff = lt_rate - ly_rate
            diff_str = f"{diff * 100:+.2f}个百分点"
            data_summary += f"  · MOB{mob}：去年同期{ly_rate * 100:.2f}%，本期{lt_rate * 100:.2f}%，差值{diff_str}\n"

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

2. 首次逾期监测（合同户数口径，统计首次达到DPD阈值的合同，单户仅计一次；在贷资产平均合同期限：{fmt_warn['平均合同期限']}）
  · 首次逾期合同数：{fmt_warn['首逾期户数']}
  · 首次逾期率：{fmt_warn['首逾期率']}
  · 平均首次逾期期数：{fmt_warn['平均首逾期期数']}  

3. 分析提示
  · 重点关注持续恶化账户的还款能力变化，防范风险进一步向下迁移
  · 首次逾期率与平均首次逾期期数共同反映前端准入质量，期数越早说明前端风险越突出，需持续跟踪新批次走势
"""
    user_prompt = data_summary.strip()

    # ========== 7. 系统提示词 ==========
    system_prompt = """
你是资深融资租赁风控专家，擅长融资租赁业务的资产质量分析。
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

    return system_prompt, user_prompt

def generate_risk_report(analysis_result):
    """生成AI资产质量分析报告"""
    try:
        # 调用统一的提示词生成函数
        system_prompt, user_prompt = build_analysis_prompts(analysis_result)

        # 调用豆包API
        client = get_ark_client()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=1800
        )

        report_content = response.choices[0].message.content.strip()

        # 兜底校验
        total_balance_fmt = f"{analysis_result['monthly_balance'].iloc[:, -1]['合计'] / 100000000:.2f}"
        if total_balance_fmt not in report_content:
            report_content = "⚠️ 【数据校验提示】报告核心余额数值可能存在偏差，请人工核对\n\n" + report_content

        return report_content

    except Exception as e:
        return f"⚠️ AI报告生成失败：{type(e).__name__} - {str(e)[:150]}"
