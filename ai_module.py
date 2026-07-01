import os
from volcenginesdkarkruntime import Ark

# ===================== API基础配置（与你官方调用格式完全一致） =====================
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
MODEL_NAME = "doubao-seed-2-1-turbo-260628"


def get_ark_client():
    """初始化Ark客户端，从系统环境变量读取密钥，避免硬编码泄露"""
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
        # ========== 1. 从分析结果中提取基础数据 ==========
        roll_rate = analysis_result["roll_rate"]                # 迁徙率表
        monthly_balance = analysis_result["monthly_balance"]    # 月度余额表
        provision = analysis_result["monthly_provision"]        # 拨备汇总表
        vintage_pivot = analysis_result["vintage_pivot"]        # Vintage透视表
        analysis_date = analysis_result["analysis_date"].strftime("%Y年%m月%d日")

        # ========== 2. 迁徙率维度数据提取 ==========
        # 筛选出纯月份列（排除「近12月平均值」）
        month_cols = [col for col in roll_rate.columns if col != "近12月平均值"]
        latest_month = month_cols[-1]  # 最新月份
        recent_6_months = month_cols[-6:]  # 近6个月
        roll_avg = roll_rate["近12月平均值"].round(4)
        roll_recent_6 = roll_rate[recent_6_months].round(4)

        # ========== 3. 资产结构维度数据提取 ==========
        balance_latest = monthly_balance[latest_month]
        total_balance = balance_latest["合计"]
        balance_share = (balance_latest / total_balance).round(4)

        # 计算M3+不良率
        m3_plus_labels = [
            "M4(91-120天)", "M5(121-150天)",
            "M6(151-180天)", "M7(181天+)"
        ]
        m3_plus_balance = balance_latest.loc[m3_plus_labels].sum()
        m3_plus_rate = m3_plus_balance / total_balance if total_balance != 0 else 0

        # 最新拨备数据
        latest_prov = provision.iloc[-1]
        provision_rate = latest_prov["整体拨备率"]

        # ========== 4. Vintage维度数据提取 ==========
        all_batches = vintage_pivot.index.tolist()
        all_mobs = vintage_pivot.columns.tolist()

        # 4.1 对标基准：最新批次的最大有效MOB
        latest_batch = all_batches[-1]
        latest_row = vintage_pivot.loc[latest_batch]
        valid_mobs_latest = [mob for mob in all_mobs if latest_row[mob] != '-']
        target_mob = max(valid_mobs_latest) if valid_mobs_latest else 1

        # 4.2 近12个批次同MOB横向对比
        same_mob_comparison = []
        for batch in all_batches:
            val = vintage_pivot.loc[batch, target_mob]
            if val != '-':
                same_mob_comparison.append((batch, float(val)))
        recent_12_same_mob = same_mob_comparison[-12:]

        # 4.3 同比对标
        latest_year, latest_month_str = latest_batch.split('-')
        last_year_batch = f"{int(latest_year)-1}-{latest_month_str}"
        yoy_rate = None
        if last_year_batch in vintage_pivot.index:
            yoy_val = vintage_pivot.loc[last_year_batch, target_mob]
            if yoy_val != '-':
                yoy_rate = float(yoy_val)

        # 4.4 成熟批次长期损失参考
        mature_batches = []
        for batch in all_batches[:-12]:
            row = vintage_pivot.loc[batch]
            valid_values = [float(x) for x in row if x != '-']
            if len(valid_values) >= 24:
                peak_rate = max(valid_values)
                mature_batches.append((batch, peak_rate))
        avg_mature_peak = sum([x[1] for x in mature_batches]) / len(mature_batches) if mature_batches else 0

        # 4.5 近6个批次逐期演化明细
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

        # ========== 5. 拼接完整 data_summary ==========
        data_summary = f"""
【一、分析基础信息】
分析基准日：{analysis_date}
业务口径：商用车 · 损失不担模式 · 剔除厂融中心
逾期判定：DPD≥16天记为逾期，M7回收率假设30%

统计规则说明（AI解读请严格遵循）：
1. M5-M6、M6-M7档位因尾部余额基数通常极小，迁徙率数值波动大且可能超过100%，属于统计基数效应，不作为核心风险判断依据，仅作参考
2. Vintage分析遵循同账龄对齐原则，仅相同MOB期数的数据可横向对比
3. 商用车融资租赁业务普遍规律：首期逾期率与批次最终峰值损失率呈强正相关，可用于辅助预判新批次长期风险

【二、资产总览与风险结构（{latest_month}）】
- 月末在贷总资产余额：{total_balance:,.2f} 元
- 当月应计提拨备金额：{latest_prov['当月应计提拨备']:,.2f} 元
- 整体拨备率：{provision_rate:.2%}
- M3+不良率：{m3_plus_rate:.2%}
- 关注类（M1-M2）合计占比：{balance_share['M1(1-30天)'] + balance_share['M2(31-60天)']:.2%}
- 损失类（M7）占比：{balance_share['M7(181天+)']:.2%}
- 各逾期等级余额占比明细：
"""
        for label in balance_share.index[:-1]:
            data_summary += f"  · {label}：{balance_share[label]:.2%}\n"

        data_summary += f"""
【三、迁徙率趋势分析】
1. 近12月平均迁徙率：
"""
        for k, v in roll_avg.items():
            data_summary += f"  · {k}：{v:.2%}\n"

        data_summary += f"\n2. 近6个月逐月迁徙率（按时间从早到晚排列）：\n"
        header = "  档位 | " + " | ".join(recent_6_months)
        data_summary += header + "\n"
        data_summary += "  " + "-" * len(header.strip()) + "\n"
        for idx in roll_recent_6.index:
            row_str = "  " + idx + " | "
            row_str += " | ".join([f"{roll_recent_6.loc[idx, m]:.2%}" for m in recent_6_months])
            data_summary += row_str + "\n"

        data_summary += f"""
【四、Vintage账龄表现】
统计规则补充：
- 同账龄对齐原则：仅相同MOB期数的逾期率可跨批次横向对比
- 单批次纵向数据：反映该批次资产风险随账龄的演化轨迹
- 成熟批次峰值：为资产充分演化后的最终损失参考，新批次账龄不足不直接对比

1. 统一对标基准：以最新批次【{latest_batch}】的最大有效账龄 MOB{target_mob} 为时点
   近12个批次同MOB逾期率（从早到晚）：
"""
        for batch, rate in recent_12_same_mob:
            data_summary += f"  · {batch}：{rate*100:.2f}%\n"

        if yoy_rate is not None:
            latest_rate = float(same_mob_comparison[-1][1])
            yoy_diff = latest_rate - yoy_rate
            data_summary += f"\n2. 同比对标（{latest_batch} vs {last_year_batch}，均为MOB{target_mob}）：\n"
            data_summary += f"  · 去年同期：{yoy_rate*100:.2f}%\n"
            data_summary += f"  · 本期：{latest_rate*100:.2f}%\n"
            data_summary += f"  · 同比差值：{yoy_diff*100:+.2f}个百分点\n"

        data_summary += f"\n3. 近{recent_batch_num}个批次逐期演化明细（按放款时间从新到旧）：\n"
        for batch, points in reversed(batch_evolution):
            point_str = "，".join([f"MOB{mob}：{rate*100:.2f}%" for mob, rate in points])
            data_summary += f"  · {batch}批次：{point_str}\n"

        if avg_mature_peak > 0:
            data_summary += f"\n4. 成熟批次长期损失参考（演化≥24期的批次峰值均值）：\n"
            data_summary += f"  · 历史平均峰值逾期率：{avg_mature_peak*100:.2f}%\n"

        # ========== 6. 构造Prompt ==========
        system_prompt = """
你是资深融资租赁风控专家，擅长商用车融资租赁业务的资产质量分析。
请基于用户提供的业务数据，撰写一份专业、严谨的月度资产质量分析报告。
要求：
1. 严格遵守数据前的【统计规则说明】，不得对尾部迁徙率过度解读，不得违反同账龄对比原则
2. 报告固定分为四个部分：
   ① 资产质量整体概览：总结资产规模、拨备水平、不良率与风险结构特征
   ② 迁徙率趋势与风险传导分析：对比近6个月变化，分析各档位迁徙走势，判断风险传导的快慢与重点环节
   ③ Vintage账龄表现解读：分析新投放资产质量的环比、同比变化趋势，结合历史成熟批次预判长期损失压力
   ④ 风控管理优化建议：分贷前、贷中、贷后三个维度给出可落地的管理建议
3. 所有结论必须基于提供的数据得出，不得凭空臆造；数据异常点需明确指出并结合业务逻辑解释
4. 语言严谨专业，符合金融机构内部报告风格，避免空泛套话
5. 全文控制在800-1000字，直接输出报告正文，不要有多余的开场白和结束语
        """.strip()

        user_prompt = data_summary.strip()

        # ========== 7. 调用豆包API ==========
        client = get_ark_client()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=1200
        )

        # 提取返回结果
        report_content = response.choices[0].message.content.strip()
        return report_content

    except Exception as e:
        return f"⚠️ AI报告生成失败：{type(e).__name__} - {str(e)[:150]}"