import pandas as pd
import warnings
import logging
from openpyxl.styles import PatternFill
from pathlib import Path

# ==================== 默认配置（界面可覆盖） ====================
DEFAULT_CONFIG = {
    "business_params": {
        "overdue_dpd_threshold": 16,
        "first_period_num": 1,
        "roll_rate_bins": [0, 1, 31, 61, 91, 121, 151, 181, float('inf')],
        "roll_rate_labels": ["M0(正常)", "M1(1-30天)", "M2(31-60天)", "M3(61-90天)",
                             "M4(91-120天)", "M5(121-150天)", "M6(151-180天)", "M7(181天+)"],
        "roll_rate_pairs": [
            ("M0(正常)", "M1(1-30天)"),
            ("M1(1-30天)", "M2(31-60天)"),
            ("M2(31-60天)", "M3(61-90天)"),
            ("M3(61-90天)", "M4(91-120天)"),
            ("M4(91-120天)", "M5(121-150天)"),
            ("M5(121-150天)", "M6(151-180天)"),
            ("M6(151-180天)", "M7(181天+)")
        ]
    },
    "required_columns": {
        "merge": ["合同号", "经销商名称", "客户名称", "起租日", "期号", "租金结算日期", "结清日期", "未偿还本金",
                  "放款金额", "业务类别", "业务模式"],
        "preprocess": ["合同号", "期号", "放款金额", "起租日", "逾期天数（DPD）", "未偿还本金"]
    }
}

warnings.filterwarnings("ignore", category=UserWarning, module='openpyxl.styles.stylesheet')


def init_logger():
    log_format = "%(asctime)s - %(levelname)s - %(module)s - %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler("vintage_analysis.log", encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


logger = init_logger()


# ==================== 1. 数据合并（改为接收DataFrame） ====================
def merge_dataframes(rent_df, asset_df):
    try:
        logger.info(f"租金收入表数据行数：{len(rent_df)}")
        logger.info(f"资产余额表数据行数：{len(asset_df)}")

        # 合并，重名列加后缀：租金表加_rent，资产表加_asset
        merged_df = pd.merge(
            rent_df,
            asset_df,
            on='合同号',
            how='inner',
            suffixes=('_rent', '_asset')
        )
        logger.info(f"两表inner合并后，数据行数：{len(merged_df)}")

        # 统一字段：客户名称、放款金额、业务模式、大区、业务来源 以资产表为准
        # 如果原租金表有同名字段，直接覆盖为资产表的值
        col_map = {
            '客户名称_asset': '客户名称',
            '放款金额_asset': '放款金额',
            '业务模式_asset': '业务模式',
            '大区_asset': '大区',
            '业务来源_asset': '业务来源'
        }
        for old_col, new_col in col_map.items():
            if old_col in merged_df.columns:
                merged_df[new_col] = merged_df[old_col]
                merged_df.drop(columns=[old_col], errors='ignore', inplace=True)
            # 删除租金表的重名列
            merged_df.drop(columns=[f"{new_col}_rent"], errors='ignore', inplace=True)

        # 日期字段标准化
        merged_df['租金结算日期'] = pd.to_datetime(merged_df['租金结算日期'], errors='coerce')
        merged_df['结清日期'] = pd.to_datetime(merged_df['结清日期'], errors='coerce')

        current_date = pd.Timestamp.now().normalize()
        merged_df['逾期天数（DPD）'] = 0

        mask_settled = merged_df['结清日期'].notna() & merged_df['租金结算日期'].notna()
        merged_df.loc[mask_settled, '逾期天数（DPD）'] = (
                merged_df.loc[mask_settled, '结清日期'] - merged_df.loc[mask_settled, '租金结算日期']
        ).dt.days

        mask_unsettled = merged_df['结清日期'].isna() & merged_df['租金结算日期'].notna()
        mask_overdue = mask_unsettled & (current_date > merged_df['租金结算日期'])
        merged_df.loc[mask_overdue, '逾期天数（DPD）'] = (
                current_date - merged_df.loc[mask_overdue, '租金结算日期']
        ).dt.days

        merged_df['逾期天数（DPD）'] = merged_df['逾期天数（DPD）'].clip(lower=0)
        merged_df.loc[merged_df['租金结算日期'].isna(), '逾期天数（DPD）'] = pd.NA

        return merged_df
    except Exception as e:
        logger.error(f"数据合并错误: {e}", exc_info=True)
        return None


# ==================== 2. 数据校验 ====================
def validate_data(df):
    df_valid = df.copy()
    invalid_records = []

    if '放款金额' in df_valid.columns and (df_valid['放款金额'] <= 0).any():
        invalid_cnt = (df_valid['放款金额'] <= 0).sum()
        invalid_records.append(f"放款金额≤0的记录数：{invalid_cnt}")
        df_valid = df_valid[df_valid['放款金额'] > 0]

    if '期号' in df_valid.columns and (df_valid['期号'] <= 0).any():
        invalid_cnt = (df_valid['期号'] <= 0).sum()
        invalid_records.append(f"期号≤0的记录数：{invalid_cnt}")
        df_valid = df_valid[df_valid['期号'] > 0]

    if '未偿还本金' in df_valid.columns and (df_valid['未偿还本金'] < 0).any():
        invalid_cnt = (df_valid['未偿还本金'] < 0).sum()
        invalid_records.append(f"未偿还本金<0的记录数：{invalid_cnt}")
        df_valid = df_valid[df_valid['未偿还本金'] >= 0]

    df_valid['起租日'] = pd.to_datetime(df_valid['起租日'], errors='coerce')
    df_valid['租金结算日期'] = pd.to_datetime(df_valid['租金结算日期'], errors='coerce')
    date_invalid = df_valid[(df_valid['起租日'].notna()) & (df_valid['租金结算日期'].notna()) &
                            (df_valid['起租日'] > df_valid['租金结算日期'])]
    if len(date_invalid) > 0:
        invalid_records.append(f"起租日晚于结算日期的记录数：{len(date_invalid)}")
        df_valid = df_valid.drop(date_invalid.index)

    if invalid_records:
        logger.warning("数据校验发现异常：")
        for record in invalid_records:
            logger.warning(f"  - {record}")
    else:
        logger.info("数据校验通过，无异常记录")

    return df_valid, invalid_records


# ==================== 3. 数据预处理 ====================
def preprocess_data(df, filter_params=None, config=None):
    if config is None:
        config = DEFAULT_CONFIG

    df, invalid_records = validate_data(df)

    if filter_params:
        for filter_col, filter_conditions in filter_params.items():
            if filter_col not in df.columns:
                logger.warning(f"筛选列{filter_col}不存在，跳过该维度筛选")
                continue
            mask = pd.Series([True] * len(df), index=df.index)
            for condition in filter_conditions:
                if 'not ' in condition:
                    keyword = condition.replace('not ', '').strip()
                    mask &= ~df[filter_col].astype(str).str.contains(keyword, na=False, regex=False)
                else:
                    keyword = condition.strip()
                    mask &= df[filter_col].astype(str).str.contains(keyword, na=False, regex=False)
            df = df[mask]
            logger.info(f"{filter_col}筛选后，数据行数：{len(df)}")

    required_columns = config["required_columns"]["preprocess"]
    for col in required_columns:
        if col not in df.columns:
            raise KeyError(f"数据集中缺少必要列: {col}")

    df['状态优先级'] = df['是否结清标志'].map({'ADV': 2, 'Y': 1}).fillna(0)
    df = df.sort_values(['合同号', '期号', '状态优先级', '结清日期'])
    df = df.groupby(['合同号', '期号'], as_index=False).tail(1)
    df = df.drop(columns=['状态优先级'])
    df = df.reset_index(drop=True)
    df['起租日'] = pd.to_datetime(df['起租日'])
    df['Vintage'] = df['起租日'].dt.to_period('M').astype(str)

    overdue_threshold = config["business_params"]["overdue_dpd_threshold"]
    df['is_overdue'] = df['逾期天数（DPD）'].apply(
        lambda x: 1 if (pd.notna(x) and x >= overdue_threshold) else 0
    )
    df_sorted = df.sort_values(['合同号', '期号'])

    contract_is_bad = df_sorted.groupby('合同号')['is_overdue'].max().reset_index()
    contract_is_bad.rename(columns={'is_overdue': 'is_bad_asset'}, inplace=True)

    first_overdue = df_sorted[df_sorted['is_overdue'] == 1].groupby('合同号').first().reset_index()
    first_overdue = first_overdue[['合同号', '期号', '未偿还本金']].rename(
        columns={'期号': '首次逾期期号', '未偿还本金': '首次逾期未偿还本金'}
    )

    df = pd.merge(df, contract_is_bad, on='合同号', how='left')
    df = pd.merge(df, first_overdue, on='合同号', how='left')
    df['首次逾期未偿还本金'] = df['首次逾期未偿还本金'].fillna(0)
    df['首次逾期期号'] = df['首次逾期期号'].fillna(0).astype(int)

    df['当期逾期本金'] = 0.0
    mask_after_overdue = df['期号'] >= df['首次逾期期号']
    df.loc[mask_after_overdue, '当期逾期本金'] = df.loc[mask_after_overdue, '首次逾期未偿还本金'].values

    return df


def fill_missing_periods(df, default_total_period=48):
    logger.warning(f"采用简便算法：仅对坏资产补全至默认{default_total_period}期")

    contract_last_period = df.groupby('合同号')['期号'].max().reset_index()
    contract_last_period.rename(columns={'期号': '实际结清期'}, inplace=True)

    contract_info = df.groupby('合同号').agg(
        是否坏资产=('is_bad_asset', 'max'),
        首次逾期未偿还本金=('首次逾期未偿还本金', 'max')
    ).reset_index()

    contract_info = pd.merge(contract_info, contract_last_period, on='合同号', how='left')

    need_fill_contracts = contract_info[
        (contract_info['是否坏资产'] == 1) &
        (contract_info['实际结清期'] < default_total_period) &
        (contract_info['实际结清期'].notna())
        ]
    logger.info(f"需补全后续期数的坏资产合同数：{len(need_fill_contracts)}")

    filled_records = []
    for _, contract in need_fill_contracts.iterrows():
        contract_id = contract['合同号']
        last_period = int(contract['实际结清期'])
        bad_principal = contract['首次逾期未偿还本金']
        base_info = df[df['合同号'] == contract_id].iloc[0].to_dict()

        for period in range(last_period + 1, default_total_period + 1):
            filled_record = base_info.copy()
            filled_record.update({
                '期号': period,
                '结清状态': '坏资产补全（默认48期）',
                '租金结算日期': pd.NaT,
                '当期逾期本金': bad_principal,
                'is_overdue': 1,
                '逾期天数（DPD）': 999,
                '未偿还本金': bad_principal
            })
            filled_records.append(filled_record)

    if filled_records:
        filled_df = pd.DataFrame(filled_records)[df.columns]
        df = pd.concat([df, filled_df], ignore_index=True)
        logger.info(f"坏资产补全完成：新增{len(filled_records)}条记录")

    return df


# ==================== 4. Vintage矩阵 ====================
def build_vintage_matrix(df):
    contract_level = df.drop_duplicates(subset=['合同号'])[
        ['合同号', 'Vintage', '放款金额']
    ]
    logger.info(f"合同级去重后的数据量：{len(contract_level)}条")

    vintage_total = contract_level.groupby('Vintage')['放款金额'].sum().reset_index(
        name='总放款金额'
    )
    vintage_total['总放款金额'] = vintage_total['总放款金额'].replace(0, pd.NA)

    vintage_mob = df.groupby(['Vintage', '期号']).agg(
        逾期本金=('当期逾期本金', 'sum')
    ).reset_index()

    vintage_mob = vintage_mob.merge(vintage_total, on='Vintage', how='left')
    vintage_mob['逾期率'] = vintage_mob.apply(
        lambda row: row['逾期本金'] / row['总放款金额'] if pd.notna(row['总放款金额']) else 0,
        axis=1
    )
    vintage_mob['逾期率'] = vintage_mob['逾期率'].replace([float('inf'), -float('inf')], 0)

    logger.info(f"Vintage矩阵构建完成：{vintage_mob['Vintage'].nunique()}个Vintage × {vintage_mob['期号'].nunique()}个MOB")
    return vintage_mob


def filter_invalid_mob(vintage_mob_matrix, analysis_date):
    valid_mask = vintage_mob_matrix['Vintage'].notna()
    vintage_mob_matrix.loc[valid_mask, 'Vintage_date'] = pd.to_datetime(
        vintage_mob_matrix.loc[valid_mask, 'Vintage'].astype(str) + '-01',
        format='%Y-%m-%d',
        errors='coerce'
    )
    vintage_mob_matrix.loc[~valid_mask, 'Vintage_date'] = pd.NaT
    vintage_mob_matrix = vintage_mob_matrix.dropna(subset=['Vintage_date'])
    vintage_mob_matrix = vintage_mob_matrix[vintage_mob_matrix['Vintage_date'] <= analysis_date]

    vintage_mob_matrix['month_diff'] = (
            (analysis_date.year - vintage_mob_matrix['Vintage_date'].dt.year) * 12
            + (analysis_date.month - vintage_mob_matrix['Vintage_date'].dt.month)
    )
    vintage_mob_matrix['max_valid_mob'] = vintage_mob_matrix['month_diff'].clip(lower=0).replace(0, 1)

    valid_mob_matrix = vintage_mob_matrix[
        vintage_mob_matrix['期号'] <= vintage_mob_matrix['max_valid_mob']
        ].copy()

    valid_mob_matrix = valid_mob_matrix.drop(columns=['Vintage_date', 'month_diff', 'max_valid_mob'])
    logger.info(f"有效MOB筛选完成：原始记录数{len(vintage_mob_matrix)} → 有效记录数{len(valid_mob_matrix)}")
    return valid_mob_matrix


# ==================== 5. 月度余额 & 迁徙率 & 拨备 ====================
def build_monthly_balance(df, analysis_date, config=None):
    if config is None:
        config = DEFAULT_CONFIG

    bins = config["business_params"]["roll_rate_bins"]
    labels = config["business_params"]["roll_rate_labels"]

    df_real = df.copy()
    contract_base = df_real.groupby('合同号').agg(
        放款金额=('放款金额', 'first'),
        起租日=('起租日', 'min')
    ).reset_index()
    contract_base = contract_base.set_index('合同号')
    contract_base = contract_base[contract_base['起租日'] >= pd.Timestamp('2023-01-01')]

    min_date = contract_base['起租日'].min()
    if pd.isna(min_date):
        logger.error("无有效起租日期，无法生成月度余额表")
        return pd.DataFrame()

    month_range = pd.period_range(start=min_date.to_period('M'), end=analysis_date.to_period('M'), freq='M')
    month_ends = [pd.Timestamp(m.end_time) for m in month_range]

    monthly_balance_list = []
    for month_end in month_ends:
        month_str = month_end.strftime('%Y-%m')
        mask_launched = contract_base['起租日'] <= month_end
        launched_contracts = contract_base[mask_launched].copy()

        if launched_contracts.empty:
            balance_series = pd.Series(0, index=labels, name=month_str)
            monthly_balance_list.append(balance_series)
            continue

        mask_settled = (
                df_real['结清日期'].notna()
                & (df_real['结清日期'] <= month_end)
                & df_real['合同号'].isin(launched_contracts.index)
        )
        df_settled = df_real[mask_settled]

        if not df_settled.empty:
            df_settled_sorted = df_settled.sort_values('期号')
            settled_principal = df_settled_sorted.groupby('合同号')['未偿还本金'].last()
        else:
            settled_principal = pd.Series(dtype='float64')

        launched_contracts['剩余本金'] = settled_principal
        launched_contracts['剩余本金'] = launched_contracts['剩余本金'].fillna(launched_contracts['放款金额'])
        contract_principal = launched_contracts[launched_contracts['剩余本金'] > 0]['剩余本金']

        if contract_principal.empty:
            balance_series = pd.Series(0, index=labels, name=month_str)
            monthly_balance_list.append(balance_series)
            continue

        mask_due_unsettled = (
                (df_real['租金结算日期'] <= month_end)
                & ((df_real['结清日期'].isna()) | (df_real['结清日期'] > month_end))
                & df_real['合同号'].isin(contract_principal.index)
        )
        df_due_unsettled = df_real[mask_due_unsettled].copy()

        if not df_due_unsettled.empty:
            df_due_unsettled['时点DPD'] = (month_end - df_due_unsettled['租金结算日期']).dt.days
            df_due_unsettled['时点DPD'] = df_due_unsettled['时点DPD'].clip(lower=0)
            contract_dpd = df_due_unsettled.groupby('合同号')['时点DPD'].max()
        else:
            contract_dpd = pd.Series(dtype='float64')

        contract_status = pd.concat([contract_dpd, contract_principal], axis=1)
        contract_status.columns = ['时点DPD', '未偿还本金']
        contract_status['时点DPD'] = contract_status['时点DPD'].fillna(0)

        contract_status['逾期等级'] = pd.cut(
            contract_status['时点DPD'],
            bins=bins,
            labels=labels,
            right=False,
            include_lowest=True
        )

        balance = contract_status.groupby('逾期等级', observed=False)['未偿还本金'].sum()
        balance.name = month_str
        monthly_balance_list.append(balance)

    monthly_balance_df = pd.concat(monthly_balance_list, axis=1).fillna(0)
    monthly_balance_df.loc['合计'] = monthly_balance_df.sum()
    logger.info(f"月度余额表生成完成，共覆盖 {len(month_range)} 个观察月")
    return monthly_balance_df


def build_roll_rate_table(monthly_balance_df, fixed_m7_recovery_rate=None, config=None):
    if config is None:
        config = DEFAULT_CONFIG
    pairs = config["business_params"]["roll_rate_pairs"]
    months = monthly_balance_df.columns.tolist()

    if len(months) < 2:
        logger.warning("观察月份不足2个，无法计算迁移率")
        return pd.DataFrame()

    roll_rate_data = {}
    valid_months = months[1:]

    for prev_label, curr_label in pairs:
        rate_name = f"{prev_label.split('(')[0]}-{curr_label.split('(')[0]}"
        monthly_rates = {}
        for i in range(1, len(months)):
            prev_month = months[i - 1]
            curr_month = months[i]
            prev_bal = monthly_balance_df.loc[prev_label, prev_month]
            curr_bal = monthly_balance_df.loc[curr_label, curr_month]
            raw_rate = curr_bal / prev_bal if prev_bal != 0 else 0
            monthly_rates[curr_month] = pd.Series([raw_rate]).clip(0, 1).iloc[0]
        roll_rate_data[rate_name] = monthly_rates

    if fixed_m7_recovery_rate is not None:
        recovery_rates = {month: fixed_m7_recovery_rate for month in valid_months}
        roll_rate_data['M7假设回收率'] = recovery_rates

    roll_rate_df = pd.DataFrame(roll_rate_data).T
    roll_rate_df['近12月平均值'] = roll_rate_df.apply(lambda x: x.dropna().tail(12).mean(), axis=1)

    cols = ['近12月平均值'] + [c for c in roll_rate_df.columns if c != '近12月平均值']
    roll_rate_df = roll_rate_df[cols]
    logger.info("迁移率表计算完成")
    return roll_rate_df


def calc_loss_rates(roll_rate_df, recovery_rate=0.3):
    roll_chain = ['M0-M1', 'M1-M2', 'M2-M3', 'M3-M4', 'M4-M5', 'M5-M6', 'M6-M7']
    level_labels = ['M0', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6']

    missing = [x for x in roll_chain if x not in roll_rate_df.index]
    if missing:
        logger.error(f"迁徙率缺少档位，无法计算损失率：{missing}")
        return pd.DataFrame()

    avg_roll = roll_rate_df.loc[roll_chain, '近12月平均值'].copy()
    avg_roll = avg_roll.clip(lower=0, upper=1)

    gross_loss_series = avg_roll[::-1].cumprod()[::-1]
    gross_loss_series.index = level_labels
    gross_loss_series['M7'] = 1.0

    net_loss_series = gross_loss_series * (1 - recovery_rate)

    loss_rates = pd.DataFrame({
        '毛损失率': gross_loss_series,
        '净损失率': net_loss_series
    })
    loss_rates.index.name = '逾期等级'
    loss_rates = loss_rates.reindex(['M0', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7'])
    logger.info("各级坏账损失率计算完成")
    return loss_rates


def calc_monthly_provision(monthly_balance_df, loss_rates_df):
    net_loss = loss_rates_df['净损失率'].copy()
    label_mapping = {
        'M0': 'M0(正常)',
        'M1': 'M1(1-30天)',
        'M2': 'M2(31-60天)',
        'M3': 'M3(61-90天)',
        'M4': 'M4(91-120天)',
        'M5': 'M5(121-150天)',
        'M6': 'M6(151-180天)',
        'M7': 'M7(181天+)'
    }
    net_loss.index = net_loss.index.map(label_mapping)

    balance = monthly_balance_df.drop(index='合计', errors='ignore')
    common_levels = balance.index.intersection(net_loss.index)

    if len(common_levels) == 0:
        logger.error("余额表与损失率的逾期等级仍无法匹配，无法计算拨备")
        return pd.DataFrame(), pd.DataFrame()

    balance = balance.loc[common_levels]
    net_loss = net_loss.loc[common_levels]

    provision_detail = balance.multiply(net_loss, axis=0)
    monthly_provision = pd.DataFrame({
        '月末总资产余额': balance.sum(axis=0),
        '当月应计提拨备': provision_detail.sum(axis=0)
    })
    monthly_provision['应计提拨备率'] = monthly_provision['当月应计提拨备'] / monthly_provision['月末总资产余额']

    logger.info("月度拨备准备金测算完成")
    return monthly_provision, provision_detail


def calc_continuous_deterioration(df_clean, min_periods=2):
    """
    识别持续恶化高风险账户：连续多期逾期等级逐期上升、无还款回落
    :param df_clean: 清洗后的合同明细表
    :param min_periods: 最小连续升档次数，2=连续升2档（如M1→M2→M3）
    :return: 高风险账户DataFrame
    """
    # 1. 逾期分箱规则（与迁徙率计算口径完全一致）
    roll_bins = [0, 1, 31, 61, 91, 121, 151, 181, float('inf')]
    roll_labels = ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7"]
    label_rank = {label: i for i, label in enumerate(roll_labels)}

    # 2. 数据预处理
    cols = ["合同号", "经销商名称", "客户名称", "期号", "逾期天数（DPD）", "未偿还本金"]
    df_risk = df_clean[cols].copy()
    df_risk = df_risk.dropna(subset=["逾期天数（DPD）"])
    df_risk["逾期等级"] = pd.cut(
        df_risk["逾期天数（DPD）"],
        bins=roll_bins,
        labels=roll_labels,
        right=False,
        include_lowest=True
    )
    df_risk["等级序号"] = df_risk["逾期等级"].map(label_rank)

    # 3. 排序与差分计算
    df_risk = df_risk.sort_values(["合同号", "期号"]).reset_index(drop=True)
    df_risk["上期等级序号"] = df_risk.groupby("合同号")["等级序号"].shift(1)
    df_risk["上期期号"] = df_risk.groupby("合同号")["期号"].shift(1)

    # 4. 双重判定：等级升档 + 期号连续（排除跳期数据）
    df_risk["是否升档"] = (
        (df_risk["等级序号"] > df_risk["上期等级序号"]) &
        (df_risk["期号"] - df_risk["上期期号"] == 1)
    )

    # 5. 连续升档计数（向量化，高性能）
    df_risk["块标识"] = (~df_risk["是否升档"]).groupby(df_risk["合同号"]).cumsum()
    df_risk["连续升档期数"] = df_risk.groupby(["合同号", "块标识"]).cumcount()

    # 6. 筛选结果并去重
    result = df_risk[df_risk["连续升档期数"] >= min_periods].copy()
    result = result.sort_values("期号", ascending=False).drop_duplicates(subset=["合同号"])
    result = result[[
        "合同号", "经销商名称", "客户名称", "期号", "逾期天数（DPD）",
        "逾期等级", "连续升档期数", "未偿还本金"
    ]].sort_values("未偿还本金", ascending=False).reset_index(drop=True)

    return result

# ==================== 统一总入口（界面只调用这一个函数） ====================
def run_full_analysis(rent_df, asset_df, filter_params=None, fixed_m7_rate=0.3,
                      overdue_dpd_threshold=None, config=None):
    """
    一键执行完整风控分析
    返回：结果字典，包含所有计算结果
    """
    if config is None:
        config = DEFAULT_CONFIG

    # ========== 新增：覆盖逾期阈值配置 ==========
    if overdue_dpd_threshold is not None:
        config["business_params"]["overdue_dpd_threshold"] = overdue_dpd_threshold

    # 1. 数据合并 + 匹配校验
    df_merged = merge_dataframes(rent_df, asset_df)
    if df_merged is None:
        return None

    # ========== 新增：数据匹配度校验 ==========
    rent_contract_count = rent_df["合同号"].nunique()
    merged_contract_count = df_merged["合同号"].nunique()
    match_rate = merged_contract_count / rent_contract_count if rent_contract_count > 0 else 0

    # 匹配率低于90%直接终止，避免错误数据产出错误结论
    if match_rate < 0.9:
        print(f"⚠️ 合同匹配率仅 {match_rate:.1%}，低于90%阈值，请检查两个表的口径、合同号格式是否一致")
        return None

    # 匹配率90%-99%给出警告（不终止，仅提示）
    if match_rate < 0.99:
        print(f"⚠️ 合同匹配率 {match_rate:.1%}，存在部分合同未匹配到余额信息，结果可能存在偏差")

    # 2. 数据预处理
    df_clean_base = preprocess_data(df_merged, filter_params, config)
    df_clean = fill_missing_periods(df_clean_base)

    # 3. Vintage分析
    vintage_mob_matrix = build_vintage_matrix(df_clean)
    today = pd.Timestamp.now()
    last_day_of_last_month = today.replace(day=1) - pd.Timedelta(days=1)
    ANALYSIS_DATE = last_day_of_last_month
    vintage_mob_valid = filter_invalid_mob(vintage_mob_matrix, ANALYSIS_DATE)
    pivot_table = vintage_mob_valid.pivot_table(
        index='Vintage',
        columns='期号',
        values='逾期率',
        aggfunc='mean'
    ).fillna('-')

    # 4. 迁徙率与拨备
    monthly_balance = build_monthly_balance(df_clean_base, ANALYSIS_DATE, config)
    roll_rate_table = build_roll_rate_table(monthly_balance, fixed_m7_rate, config)
    loss_rates = calc_loss_rates(roll_rate_table, recovery_rate=fixed_m7_rate)
    monthly_provision, provision_detail = calc_monthly_provision(monthly_balance, loss_rates)

    # 5. 首次逾期明细（容错：只取存在的列）
    detail_cols = [
        'Vintage', '合同号', '经销商名称', '客户名称', '大区', '业务来源', '起租日', '期号',
        '放款金额', '未偿还本金', '逾期天数（DPD）', '首次逾期期号', '首次逾期未偿还本金'
    ]
    # 过滤出实际存在的列
    available_cols = [col for col in detail_cols if col in df_clean.columns]
    overdue_records = df_clean[df_clean['is_overdue'] == 1][available_cols]

    first_overdue_only = overdue_records.sort_values(by=['合同号', '期号']) \
        .groupby('合同号').first().reset_index()
    first_overdue_only = first_overdue_only[first_overdue_only['首次逾期未偿还本金'] > 0.01]
    first_overdue_only = first_overdue_only.sort_values(by=['Vintage', '期号', '合同号'])
    continuous_deterioration = calc_continuous_deterioration(df_clean_base, min_periods=2)   # 新增：持续恶化高风险账户识别

    return {
        "df_clean": df_clean,
        "vintage_pivot": pivot_table,
        "vintage_detail": vintage_mob_valid,
        "monthly_balance": monthly_balance,
        "roll_rate": roll_rate_table,
        "loss_rates": loss_rates,
        "monthly_provision": monthly_provision,
        "provision_detail": provision_detail,
        "first_overdue": first_overdue_only,
        "analysis_date": ANALYSIS_DATE,
        "continuous_deterioration": continuous_deterioration,
        "match_rate": match_rate,
        "overdue_threshold": config["business_params"]["overdue_dpd_threshold"]  # 新增这行
    }
