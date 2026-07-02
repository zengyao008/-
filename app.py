import streamlit as st
import pandas as pd
import plotly.express as px
import io
import risk_analysis as ra
from ai_module import generate_risk_report


def read_uploaded_file(uploaded_file):
    """
    自动识别文件格式（CSV/Excel），兼容编码问题，返回DataFrame
    """
    if uploaded_file is None:
        return None

    filename = uploaded_file.name.lower()
    try:
        # CSV格式：自动尝试UTF-8、GBK双编码，解决中文乱码问题
        if filename.endswith(".csv"):
            try:
                return pd.read_csv(uploaded_file, encoding="utf-8")
            except UnicodeDecodeError:
                uploaded_file.seek(0)  # 重置文件指针，避免二次读取为空
                return pd.read_csv(uploaded_file, encoding="gbk")

        # Excel格式：支持xlsx、xls
        elif filename.endswith((".xlsx", ".xls")):
            return pd.read_excel(uploaded_file)

        # 不支持的格式
        else:
            suffix = filename.split(".")[-1]
            raise ValueError(f"不支持的文件格式 .{suffix}，仅支持 .csv / .xlsx / .xls")

    except Exception as e:
        raise e


# 页面全局配置
st.set_page_config(
    page_title="通盛租赁资产AI助手",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========== 全局品牌样式（增强版） ==========
st.markdown("""
<style>
    /* 全局基础：内容区边距优化，不贴边 */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 95%;
    }

    /* 标题统一品牌深蓝，字重更沉稳 */
    h1, h2, h3 {
        color: #003D8C;
        font-weight: 600;
        letter-spacing: 0.3px;
    }

    /* 主按钮：品牌深蓝 + 平滑过渡 */
    .stButton > button[kind="primary"] {
        background-color: #003D8C;
        border: 1px solid #003D8C;
        transition: all 0.2s ease;
        font-weight: 500;
    }
    .stButton > button[kind="primary"]:hover {
        background-color: #002E69;
        border-color: #002E69;
        transform: translateY(-1px);
        box-shadow: 0 2px 6px rgba(0, 61, 140, 0.25);
    }
    .stButton > button[kind="primary"]:active {
        transform: translateY(0);
    }

    /* 次按钮：描边风格，统一色系 */
    .stButton > button {
        border-radius: 6px;
        border: 1px solid #CBD5E1;
    }
    .stButton > button:hover {
        border-color: #003D8C;
        color: #003D8C;
    }

    /* 指标卡片：金色左边栏 + 浅灰底 + 悬浮效果 */
    .stMetric {
        background: #F8FAFC;
        padding: 16px 20px;
        border-radius: 8px;
        border-left: 4px solid #F5B700;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        transition: all 0.2s ease;
    }
    .stMetric:hover {
        box-shadow: 0 3px 8px rgba(0,0,0,0.08);
    }
    .stMetric [data-testid="stMetricValue"] {
        color: #003D8C;
        font-weight: 600;
    }
    .stMetric [data-testid="stMetricLabel"] {
        color: #475569;
        font-weight: 500;
    }

    /* 侧边栏底色微调 + 导航美化 */
    section[data-testid="stSidebar"] {
        background: #FAFBFC;
        border-right: 1px solid #E2E8F0;
    }
    /* 侧边栏导航选中项高亮 */
    section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:has(input:checked) {
        background: #E6EFFB;
        border-left: 3px solid #003D8C;
        color: #003D8C;
        font-weight: 500;
    }
    section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label {
        padding: 8px 12px;
        border-radius: 4px;
        margin-bottom: 2px;
        transition: background 0.15s ease;
    }
    section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:hover {
        background: #F1F5F9;
    }

    /* Tab标签页品牌化 */
    button[data-baseweb="tab"] {
        color: #64748B;
        font-weight: 500;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #003D8C;
        border-color: #003D8C !important;
    }
    button[data-baseweb="tab"]:hover {
        color: #003D8C;
    }

    /* 表格表头品牌色 */
    [data-testid="stDataFrame"] thead th {
        background-color: #F0F5FC !important;
        color: #003D8C !important;
        font-weight: 600 !important;
    }

    /* 分隔线弱化，更高级 */
    hr {
        border: none;
        border-top: 1px solid #E2E8F0;
        margin: 1.2rem 0;
    }

    /* 提示框配色贴合品牌 */
    .stAlert {
        border-radius: 6px;
        border-left: 4px solid;
    }
    .stAlert[data-testid="stInfo"] {
        border-left-color: #003D8C;
        background: #F0F5FC;
    }
    .stAlert[data-testid="stSuccess"] {
        border-left-color: #059669;
        background: #ECFDF5;
    }
    .stAlert[data-testid="stWarning"] {
        border-left-color: #D97706;
        background: #FFFBEB;
    }
    .stAlert[data-testid="stError"] {
        border-left-color: #DC2626;
        background: #FEF2F2;
    }

    /* 下拉框、输入框聚焦时品牌色 */
    .stSelectbox [data-baseweb="select"]:focus-within,
    .stNumberInput [data-baseweb="input"]:focus-within {
        border-color: #003D8C;
        box-shadow: 0 0 0 3px rgba(0, 61, 140, 0.1);
    }
</style>
""", unsafe_allow_html=True)

# 全局会话状态初始化
if "analysis_result" not in st.session_state:
    st.session_state["analysis_result"] = None
if "ai_report" not in st.session_state:
    st.session_state["ai_report"] = None

# 侧边栏导航
with st.sidebar:
    # ========== 纯文字品牌区 ==========
    st.markdown("""
    <div style="padding: 8px 4px 16px 4px;">
        <div style="font-size: 20px; font-weight: 700; color: #003D8C; letter-spacing: 1px;">
            通盛租赁
        </div>
        <div style="font-size: 14px; color: #64748B; margin-top: 2px; font-weight: 500;">
            资产AI助手
        </div>
        <div style="height: 2px; width: 36px; background: #F5B700; margin-top: 10px; border-radius: 2px;"></div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    page = st.radio(
        "功能导航",
        ["首页介绍", "数据上传清洗", "风控分析看板", "风险预警中心", "AI智能解读"]
    )
    st.markdown("---")
    st.caption("授信评审部 · 资产监控工具")


# ========== 1. 首页介绍 ==========
if page == "首页介绍":
    st.header("通盛租赁资产监控AI助手")
    st.subheader("赋能风控评审 · 提升资产质效")
    st.markdown("---")

    # 核心价值指标
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("分析效率", "提升80%", "替代手工计算")
    col2.metric("口径统一", "100%", "标准化统计规则")
    col3.metric("风险识别", "前置30天", "异常动态预警")
    col4.metric("报告产出", "分钟级", "AI自动生成")

    st.markdown("---")
    st.subheader("核心功能模块")

    col_a, col_b = st.columns(2)
    with col_a:
        st.info("""
        **📊 多维度风控分析**
        - Vintage账龄分析，同账龄横向对标
        - 月度迁徙率矩阵，量化风险传导
        - 损失率测算与拨备自动计提
        """)
        st.success("""
        **⚠️ 智能风险预警**
        - 持续恶化账户精准识别
        - 大额逾期资产优先级排序
        - 异常波动自动标记
        """)
    with col_b:
        st.warning("""
        **🤖 AI智能解读**
        - 专业分析报告一键生成
        - 严格遵循风控统计规则
        - 分维度给出管理建议
        """)
        st.error("""
        **📥 结果一键导出**
        - 无缝对接日常工作流
        - AI报告文本下载
        - 分析结果Excel导出
        """)

    st.markdown("---")
    st.caption("面向授信评审部日常工作开发，可直接落地复用")

# ========== 2. 数据上传清洗 ==========
elif page == "数据上传清洗":
    st.header("数据上传与智能清洗")
    st.caption("注：分析数据口径以租金收入表为主，资产余额表可使用系统全量数据")

    col1, col2 = st.columns(2)
    with col1:
        rent_file = st.file_uploader(
            "上传【租金收入表】",
            type=["csv", "xlsx", "xls"],  # 同时支持CSV和Excel
            help="支持 CSV / Excel 格式，系统自动识别"
        )
    with col2:
        asset_file = st.file_uploader(
            "上传【资产余额表】",
            type=["csv", "xlsx", "xls"],  # 同时支持CSV和Excel
            help="支持 CSV / Excel 格式，系统自动识别"
        )

    st.subheader("分析口径配置")
    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        overdue_threshold = st.number_input(
            "Vintage逾期判定阈值（天）",
            min_value=1,
            max_value=121,
            value=16,
            step=1,
            help="DPD≥该值则计入逾期，影响Vintage逾期率（分子是否计入逾期）、首次逾期明细（首逾率）、大额逾期Top榜等统计口径"
        )
    with col_cfg2:
        m7_recovery = st.number_input(
            "M7固定回收率假设",
            min_value=0.0,
            max_value=1.0,
            value=0.3,
            step=0.05,
            help = "逾期阶段达到M7后，预期还能回收的剩余本金比例"
        )

    start_analysis = st.button("开始一键分析", type="primary", width='stretch')

    if start_analysis:
        if not rent_file or not asset_file:
            st.error("请先上传两个数据文件")
        else:
            with st.spinner("正在执行数据清洗与分析，请稍候..."):
                # 读取文件（自动适配CSV/Excel，兼容编码）
                try:
                    rent_df = read_uploaded_file(rent_file)
                    asset_df = read_uploaded_file(asset_file)
                except Exception as e:
                    st.error(f"文件读取失败，请检查格式与列名是否匹配：{str(e)[:120]}")
                    st.stop()

                # 组装筛选参数
                filter_params = {}

                # 调用核心计算模块
                result = ra.run_full_analysis(
                    rent_df,
                    asset_df,
                    filter_params=filter_params,
                    fixed_m7_rate=m7_recovery,
                    overdue_dpd_threshold=overdue_threshold
                )

                if result is None:
                    st.error("分析执行失败，请检查数据列名是否匹配")
                else:
                    # 保存到 session_state，其他页面也能用
                    st.session_state["analysis_result"] = result
                    st.success("✅ 分析完成！可前往「风控分析看板」查看详细结果")

                    # 展示清洗概览
                    st.subheader("数据清洗概览")
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("有效合同数", f"{result['df_clean']['合同号'].nunique()} 个")
                    col2.metric("总数据行数", f"{len(result['df_clean'])} 条")
                    col3.metric("分析基准日", result["analysis_date"].strftime("%Y-%m-%d"))
                    col4.metric("合同匹配率", f"{result['match_rate']*100:.1f}%")    # 新增匹配率展示

# ========== 3. 风控分析看板 ==========
elif page == "风控分析看板":
    st.header("风控分析看板")

    if st.session_state["analysis_result"] is None:
        st.warning("请先在「数据上传清洗」页面上传文件并执行分析")
    else:
        res = st.session_state["analysis_result"]

        tab1, tab2, tab3, tab4 = st.tabs(["Vintage分析", "迁徙率分析", "损失率与拨备", "首次逾期明细"])

        # Tab1: Vintage
        with tab1:
            st.subheader("Vintage 账龄分析")
            st.caption(f"当前口径：DPD≥{res['overdue_threshold']}天计入逾期 | 遵循同账龄对齐原则，仅相同MOB期数的数据可跨批次横向对比")

            # ========== 顶部核心指标 ==========
            vintage_pivot = res["vintage_pivot"]
            all_batches = vintage_pivot.index.tolist()
            all_mobs = vintage_pivot.columns.tolist()

            col1, col2, col3 = st.columns(3)
            # 指标1：最新批次首期逾期率
            latest_batch = all_batches[-1]
            mob1_rate = vintage_pivot.loc[latest_batch, 1] if 1 in all_mobs and vintage_pivot.loc[
                latest_batch, 1] != '-' else None
            col1.metric(
                "最新批次首期逾期率",
                f"{mob1_rate * 100:.2f}%" if mob1_rate is not None else "暂无数据",
                help=f"批次：{latest_batch}，MOB1"
            )
            # 指标2：最长账龄批次当前逾期率
            oldest_batch = all_batches[0]
            max_mob = max([m for m in all_mobs if vintage_pivot.loc[oldest_batch, m] != '-'], default=1)
            oldest_rate = vintage_pivot.loc[oldest_batch, max_mob] if vintage_pivot.loc[
                                                                          oldest_batch, max_mob] != '-' else None
            col2.metric(
                "最长账龄批次逾期率",
                f"{oldest_rate * 100:.2f}%" if oldest_rate is not None else "暂无数据",
                help=f"批次：{oldest_batch}，MOB{max_mob}"
            )
            # 指标3：有效分析批次总数
            col3.metric("有效分析批次", f"{len(all_batches)} 个")

            st.markdown("---")

            # ========== 批次筛选器 ==========
            plot_data = res["vintage_detail"].copy()
            batch_list = sorted(plot_data["Vintage"].unique())
            default_select = batch_list[-12:] if len(batch_list) >= 12 else batch_list
            selected_batches = st.multiselect(
                "选择展示批次",
                options=batch_list,
                default=default_select,
                help="默认展示最近12个放款批次，可自定义勾选"
            )
            plot_data_filtered = plot_data[plot_data["Vintage"].isin(selected_batches)]

            # ========== Vintage折线图（上移） ==========
            st.subheader("逾期率演化趋势")
            fig = px.line(
                plot_data_filtered,
                x="期号",
                y="逾期率",
                color="Vintage",
                markers=True,
                title="各批次账龄逾期率演化曲线",
                color_discrete_sequence=px.colors.sequential.Reds,
                hover_data={"Vintage": True, "期号": True, "逾期率": ":.2%"}
            )
            fig.update_layout(
                yaxis_tickformat=".2%",
                legend_title_text="放款批次",
                xaxis_title="账龄（MOB）",
                yaxis_title="逾期率"
            )
            st.plotly_chart(fig, width='stretch')

            st.markdown("---")

            # ========== Vintage矩阵表（下移） ==========
            st.subheader("逾期率矩阵明细")
            pivot_show = vintage_pivot.copy()
            for col in pivot_show.columns:
                pivot_show[col] = pivot_show[col].apply(
                    lambda x: f"{x * 100:.2f}%" if isinstance(x, (int, float)) else x
                )
            st.dataframe(
                pivot_show,
                width='stretch',
                height=420
            )

        # Tab2: 迁徙率
        with tab2:
            st.subheader("月度迁徙率分析")
            st.caption("注：迁徙率为月末时点快照口径；M5-M7档位尾部余额基数小，数值波动大，仅作参考，不作为核心判断依据")

            # ========== 顶部核心指标 ==========
            roll_rate = res["roll_rate"]
            month_cols = [col for col in roll_rate.columns if col != "近12月平均值"]
            latest_month = month_cols[-1]

            col1, col2, col3 = st.columns(3)

            # 指标1：前端入口 M0-M1
            if "M0-M1" in roll_rate.index:
                m0m1_latest = roll_rate.loc["M0-M1", latest_month]
                m0m1_avg = roll_rate.loc["M0-M1", "近12月平均值"]
                m0m1_delta = (m0m1_latest - m0m1_avg) * 100
                col1.metric(
                    label="M0-M1 当月迁徙率",
                    value=f"{m0m1_latest*100:.2f}%",
                    delta=f"{m0m1_delta:+.2f} 个百分点",
                    delta_color="inverse",  # 上升为风险升高，标红
                    help="前端风险入口：反映新增首期逾期压力，数值越高说明新逾期越多，下方小标数据为当月迁徙率与近12月迁徙率均值的差额"
                )
            else:
                col1.metric("M0-M1 当月迁徙率", "暂无数据")

            # 指标2：中段传导 M1-M2
            if "M1-M2" in roll_rate.index:
                m1m2_latest = roll_rate.loc["M1-M2", latest_month]
                m1m2_avg = roll_rate.loc["M1-M2", "近12月平均值"]
                m1m2_delta = (m1m2_latest - m1m2_avg) * 100
                col2.metric(
                    label="M1-M2 当月迁徙率",
                    value=f"{m1m2_latest*100:.2f}%",
                    delta=f"{m1m2_delta:+.2f} 个百分点",
                    delta_color="inverse",
                    help="中段风险传导：反映关注类资产恶化速度，是贷中管理的核心节点"
                )
            else:
                col2.metric("M1-M2 当月迁徙率", "暂无数据")

            # 指标3：不良关口 M2-M3
            if "M2-M3" in roll_rate.index:
                m2m3_latest = roll_rate.loc["M2-M3", latest_month]
                m2m3_avg = roll_rate.loc["M2-M3", "近12月平均值"]
                m2m3_delta = (m2m3_latest - m2m3_avg) * 100
                col3.metric(
                    label="M2-M3 当月迁徙率",
                    value=f"{m2m3_latest*100:.2f}%",
                    delta=f"{m2m3_delta:+.2f} 个百分点",
                    delta_color="inverse",
                    help="不良认定关口：M3及以上计入不良，此档位直接影响不良率走势"
                )
            else:
                col3.metric("M2-M3 当月迁徙率", "暂无数据")

            st.markdown("---")

            # ========== 月份范围选择器 ==========
            month_range = st.radio(
                "展示时间范围",
                options=["近3个月", "近6个月", "近12个月"],
                index=1,
                horizontal=True
            )
            range_map = {"近3个月": 3, "近6个月": 6, "近12个月": 12}
            show_month_num = range_map[month_range]
            show_months = month_cols[-show_month_num:]

            # ========== 迁徙率热力图（上移） ==========
            st.subheader("迁徙率趋势热力图")
            roll_heat_data = roll_rate[show_months].copy()
            # 过滤掉尾部参考档位，聚焦核心风险传导
            core_gears = ["M0-M1", "M1-M2", "M2-M3", "M3-M4", "M4-M5"]
            roll_heat_core = roll_heat_data[roll_heat_data.index.isin(core_gears)]

            fig_heat = px.imshow(
                roll_heat_core,
                text_auto=".2%",
                color_continuous_scale="Reds",
                aspect="auto",
                zmin=0,
                zmax=1,
                title="核心档位月度迁徙率变化"
            )
            fig_heat.update_layout(
                xaxis_title="月份",
                yaxis_title="迁徙档位",
                coloraxis_colorbar_title="迁徙率",
                coloraxis_colorbar_tickformat=".0%"
            )
            st.plotly_chart(fig_heat, width='stretch')

            st.markdown("---")

            # ========== 迁徙率明细表格（下移） ==========
            st.subheader("全档位统计表")
            roll_show = roll_rate.copy()
            for col in roll_show.columns:
                roll_show[col] = roll_show[col].apply(lambda x: f"{x * 100:.2f}%" if isinstance(x, (int, float)) else x)
            st.dataframe(
                roll_show,
                width='stretch',
                height=400
            )

        # Tab3: 损失率与拨备
        with tab3:
            st.subheader("损失率与拨备测算")
            st.caption("注：损失率基于月度迁徙率滚动计算，M7档位采用固定回收率假设，最终结果用于拨备计提参考")

            # 顶部核心指标
            col1, col2, col3 = st.columns(3)
            latest_prov = res["monthly_provision"].iloc[-1]
            col1.metric("当月计提拨备", f"{latest_prov['当月应计提拨备'] / 10000:.2f} 万元")
            col2.metric("应计提拨备率", f"{latest_prov['应计提拨备率']*100:.2f}%")
            max_loss = res["loss_rates"].max().iloc[0]
            col3.metric("单档最高毛损失率", f"{max_loss*100:.2f}%")

            st.markdown("---")

            # 月度拨备趋势图
            st.subheader("月度拨备走势（近6个月）")
            prov_trend = res["monthly_provision"].tail(6).copy()
            prov_trend["月份"] = prov_trend.index
            prov_trend["当月应计提拨备_万元"] = prov_trend["当月应计提拨备"] / 10000

            fig_prov = px.bar(
                prov_trend,
                x="月份",
                y="当月应计提拨备_万元",
                title="月度拨备金额与拨备率走势",
                color_discrete_sequence=["#e74c3c"],
                text_auto=".2s"
            )
            # 增加折线次坐标轴
            fig_prov.add_scatter(
                x=prov_trend["月份"],
                y=prov_trend["应计提拨备率"],
                mode="lines+markers",
                name="应计提拨备率",
                yaxis="y2",
                line=dict(color="#2c3e50", width=2)
            )
            fig_prov.update_layout(
                yaxis2=dict(
                    title="拨备率",
                    overlaying="y",
                    side="right",
                    tickformat=".2%"
                ),
                yaxis_title="拨备金额（万元）",
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_prov, width='stretch')

            st.markdown("---")
            col_left, col_right = st.columns(2)
            with col_left:
                st.subheader("各级毛损失率对比")
                loss_plot = res["loss_rates"].copy().reset_index()
                loss_plot = loss_plot.iloc[:, [0, 1]].copy()
                loss_plot.columns = ["逾期档位", "毛损失率"]
                fig_loss = px.bar(
                    loss_plot,
                    x="毛损失率",
                    y="逾期档位",
                    orientation="h",
                    color="毛损失率",
                    color_continuous_scale="Reds",
                    text_auto=".2%",
                    title="各逾期档位预期毛损失率"
                )
                fig_loss.update_layout(xaxis_tickformat=".2%", showlegend=False)
                st.plotly_chart(fig_loss, width='stretch')

            with col_right:
                st.subheader("各级损失率明细")
                loss_show = res["loss_rates"].copy()
                for col in loss_show.columns:
                    loss_show[col] = loss_show[col].apply(lambda x: f"{x*100:.2f}%")
                st.dataframe(loss_show, width='stretch')

            st.subheader("月度拨备汇总")
            prov_show = res["monthly_provision"].copy()
            prov_show["应计提拨备率"] = prov_show["应计提拨备率"].apply(lambda x: f"{x*100:.2f}%")
            st.dataframe(prov_show, width='stretch')

        # Tab4: 首次逾期明细
        with tab4:
            st.subheader("首次逾期明细")
            st.caption("注：首次逾期指合同生命周期内第一次出现逾期的记录，用于衡量贷前准入质量与前端风险暴露速度")

            first_ovd = res["first_overdue"].copy()

            # 顶部核心指标
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("首逾期合同数", f"{len(first_ovd)} 户")
            col2.metric("涉及未偿本金", f"{first_ovd['未偿还本金'].sum() / 10000:.0f} 万元")
            avg_dpd = first_ovd['逾期天数（DPD）'].mean() if len(first_ovd) > 0 else 0
            col3.metric("平均首次逾期天数", f"{avg_dpd:.0f} 天")
            # 计算笔数逾率
            total_contracts = res["df_clean"]["合同号"].nunique()
            first_rate = len(first_ovd) / total_contracts if total_contracts > 0 else 0
            col4.metric("合同笔数逾期率", f"{first_rate*100:.2f}%")

            st.markdown("---")

            # 按Vintage批次首逾期分布
            if len(first_ovd) > 0 and "Vintage" in first_ovd.columns:
                st.subheader("各批次首逾期分布")
                batch_first = first_ovd.groupby("Vintage").agg(
                    首逾期户数=("合同号", "nunique"),
                    涉及本金=("首次逾期未偿还本金", "sum")
                ).reset_index().sort_values("Vintage")
                fig_first = px.bar(
                    batch_first,
                    x="Vintage",
                    y="首逾期户数",
                    text="首逾期户数",
                    color="涉及本金",
                    color_continuous_scale="Reds",
                    title="各放款批次首次逾期户数分布"
                )
                st.plotly_chart(fig_first, width='stretch')

            st.markdown("---")
            st.subheader("首次逾期明细清单")
            st.dataframe(first_ovd, width='stretch')

# ========== 4. 风险预警中心 ==========
elif page == "风险预警中心":
    st.header("风险预警中心")

    if st.session_state["analysis_result"] is None:
        st.warning("请先上传数据并执行分析")
    else:
        res = st.session_state["analysis_result"]
        df_clean = res["df_clean"]

        tab1, tab2 = st.tabs(["持续恶化预警", "大额逾期Top榜"])

        # Tab1：持续恶化高风险账户
        with tab1:
            st.subheader("持续恶化高风险账户")
            st.caption("定义：连续多期逾期等级逐期上升、无还款回落，属于还款能力/意愿持续恶化的高风险资产")

            continuous_df = res["continuous_deterioration"]

            col1, col2, col3 = st.columns(3)
            col1.metric("持续恶化高风险合同数", f"{len(continuous_df)} 户")
            col2.metric("涉及未偿还本金", f"{continuous_df['未偿还本金'].sum() / 10000:,.2f} 万元")
            avg_periods = continuous_df['连续升档期数'].mean() if len(continuous_df) > 0 else 0
            col3.metric("平均连续恶化期数", f"{avg_periods:.1f} 期")

            st.markdown("---")

            if len(continuous_df) > 0:
                col_chart1, col_chart2 = st.columns(2)
                with col_chart1:
                    st.subheader("逾期等级分布")
                    st.caption("tip：连续迁徙高风险项目的阶段分布")
                    level_count = continuous_df.groupby("逾期等级")["合同号"].nunique().reset_index()
                    level_count.columns = ["逾期等级", "合同数"]
                    fig_pie = px.pie(
                        level_count,
                        names="逾期等级",
                        values="合同数",
                        color_discrete_sequence=px.colors.sequential.Reds,
                        hole=0.4,
                        title="高风险账户逾期等级占比"
                    )
                    st.plotly_chart(fig_pie, width='stretch')

                with col_chart2:
                    # 只有存在经销商名称列才渲染图表
                    if "经销商名称" in continuous_df.columns:
                        st.subheader("高风险经销商Top10")
                        st.caption("tip：此处涉及的剩余本金，仅为连续迁徙高风险项目的本金和")
                        dealer_top = continuous_df.groupby("经销商名称").agg(
                            合同数=("合同号", "nunique"),
                            涉及本金=("未偿还本金", "sum")
                        ).sort_values("涉及本金", ascending=False).head(10).reset_index()
                        fig_dealer = px.bar(
                            dealer_top,
                            x="涉及本金",
                            y="经销商名称",
                            orientation="h",
                            color="合同数",
                            color_continuous_scale="Reds",
                            title="按涉及本金排序Top10经销商"
                        )
                        fig_dealer.update_layout(yaxis={"categoryorder": "total ascending"})
                        st.plotly_chart(fig_dealer, width='stretch')
                    else:
                        st.info("暂无经销商维度数据")

            st.markdown("---")
            st.subheader("高风险账户明细")
            st.dataframe(continuous_df, width='stretch')

        # Tab2：大额逾期Top榜
        with tab2:
            st.subheader("大额逾期合同Top20")
            st.caption("按未偿还本金降序排列，聚焦头部大额风险敞口，优先跟进处置")

            top_overdue = df_clean[df_clean["is_overdue"] == 1].drop_duplicates(subset=["合同号"])[
                ["合同号", "客户名称", "经销商名称", "逾期天数（DPD）", "未偿还本金"]
            ].sort_values("未偿还本金", ascending=False).head(20).reset_index(drop=True)

            # 顶部集中度指标
            col1, col2, col3 = st.columns(3)
            top_total = top_overdue["未偿还本金"].sum()
            total_ovd_amount = df_clean[df_clean["is_overdue"] == 1].drop_duplicates(subset=["合同号"])["未偿还本金"].sum()
            concentrate_rate = top_total / total_ovd_amount if total_ovd_amount > 0 else 0
            col1.metric("Top20合计本金", f"{top_total / 10000:.2f} 万元")
            col2.metric("占总逾期本金比例", f"{concentrate_rate*100:.2f}%")
            avg_dpd_top = top_overdue["逾期天数（DPD）"].mean() if len(top_overdue) > 0 else 0
            col3.metric("平均逾期天数", f"{avg_dpd_top:.1f} 天")

            st.markdown("---")

            if len(top_overdue) > 0:
                st.subheader("大额逾期本金分布")
                fig_top = px.bar(
                    top_overdue,
                    x="未偿还本金",
                    y="客户名称",
                    orientation="h",
                    color="逾期天数（DPD）",
                    color_continuous_scale="Reds",
                    title="Top20逾期合同本金排序",
                    hover_data=["合同号", "经销商名称"]
                )
                fig_top.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig_top, width='stretch')

            st.markdown("---")
            st.subheader("大额逾期明细")
            st.dataframe(top_overdue, width='stretch')

# ========== 5. AI智能解读 ==========
elif page == "AI智能解读":
    st.header("AI智能资产质量解读")
    st.caption("基于豆包大模型，自动生成专业风控分析报告")

    if st.session_state["analysis_result"] is None:
        st.warning("请先在「数据上传清洗」页面上传文件并执行分析")
    else:
        st.success("✅ 已检测到分析数据，点击下方按钮生成AI报告")

        col_btn, col_space = st.columns([1, 3])
        with col_btn:
            generate_btn = st.button("生成AI分析报告", type="primary", width='stretch')

        # 点击生成按钮
        if generate_btn:
            with st.spinner("正在调用大模型生成分析报告，约需1-2分钟..."):
                try:
                    report = generate_risk_report(st.session_state["analysis_result"])
                    st.session_state["ai_report"] = report
                except Exception as e:
                    st.error(f"报告生成失败：{str(e)}")

        # 展示报告（仅在报告真实生成后渲染）
        if st.session_state["ai_report"] is not None:
            st.markdown("---")
            st.subheader("📄 月度资产质量分析报告")
            st.markdown(st.session_state["ai_report"])

            # 报告下载
            st.markdown("---")
            col1, col2 = st.columns([1, 4])
            with col1:
                st.download_button(
                    label="下载报告文本",
                    data=st.session_state["ai_report"],
                    file_name="AI资产质量分析报告.txt",
                    mime="text/plain",
                    width='stretch'
                )

# ========== 全局页脚 ==========
st.markdown("""
<div style="text-align: center; color: #94A3B8; font-size: 12px; margin-top: 40px; padding-top: 16px; border-top: 1px solid #E2E8F0;">
    广西通盛融资租赁有限公司 · 授信评审部 · 资产质量监控工具 v1.0
</div>
""", unsafe_allow_html=True)
