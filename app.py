import streamlit as st
import pandas as pd
import plotly.express as px
import risk_analysis as ra
from ai_module import generate_risk_report

# 页面全局配置
st.set_page_config(
    page_title="商用车融资租赁资产监控AI助手",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 侧边栏导航
with st.sidebar:
    st.title("资产监控AI助手")
    st.markdown("---")
    page = st.radio(
        "功能导航",
        ["首页介绍", "数据上传清洗", "风控分析看板", "风险预警中心", "AI智能解读"]
    )
    st.markdown("---")
    st.caption("商用车融资租赁 · 风控分析工具")

# ========== 1. 首页介绍 ==========
if page == "首页介绍":
    st.header("商用车融资租赁资产监控AI助手")
    st.subheader("赋能风控评审 · 提升资产质效")
    st.markdown("""
    本工具针对商用车融资租赁业务资产监控场景，实现：
    - 台账数据自动清洗与标准化
    - 迁徙率/Vintage/拨备一键测算
    - 异常风险智能识别与预警
    - AI驱动的业务解读与报告生成
    """)
    st.info("面向授信评审部日常工作开发，可直接落地复用")

# ========== 2. 数据上传清洗 ==========
elif page == "数据上传清洗":
    st.header("数据上传与智能清洗")

    col1, col2 = st.columns(2)
    with col1:
        rent_file = st.file_uploader("上传【租金收入表】CSV", type=["csv"])
    with col2:
        asset_file = st.file_uploader("上传【资产余额表】Excel", type=["xlsx"])


    start_analysis = st.button("开始一键分析", type="primary", use_container_width=True)

    if start_analysis:
        if not rent_file or not asset_file:
            st.error("请先上传两个数据文件")
        else:
            with st.spinner("正在执行数据清洗与分析，请稍候..."):
                # 读取文件
                rent_df = pd.read_csv(rent_file)
                asset_df = pd.read_excel(asset_file)

                # 组装筛选参数
                filter_params = {
                    "大区": ["not 厂融中心"]
                }


                # 调用核心计算模块
                result = ra.run_full_analysis(
                    rent_df,
                    asset_df,
                    filter_params=filter_params
                )

                if result is None:
                    st.error("分析执行失败，请检查数据列名是否匹配")
                else:
                    # 保存到 session_state，其他页面也能用
                    st.session_state["analysis_result"] = result
                    st.success("✅ 分析完成！可前往「风控分析看板」查看详细结果")

                    # 展示清洗概览
                    st.subheader("数据清洗概览")
                    col1, col2, col3 = st.columns(3)
                    col1.metric("有效合同数", f"{result['df_clean']['合同号'].nunique()} 个")
                    col2.metric("总数据行数", f"{len(result['df_clean'])} 条")
                    col3.metric("分析基准日", result["analysis_date"].strftime("%Y-%m-%d"))

# ========== 3. 风控分析看板 ==========
elif page == "风控分析看板":
    st.header("风控分析看板")

    if "analysis_result" not in st.session_state:
        st.warning("请先在「数据上传清洗」页面上传文件并执行分析")
    else:
        res = st.session_state["analysis_result"]

        tab1, tab2, tab3, tab4 = st.tabs(["Vintage分析", "迁徙率分析", "损失率与拨备", "首次逾期明细"])

        # Tab1: Vintage
        with tab1:
            st.subheader("Vintage 逾期率矩阵")
            # 格式化百分比展示
            pivot_show = res["vintage_pivot"].copy()
            for col in pivot_show.columns:
                pivot_show[col] = pivot_show[col].apply(
                    lambda x: f"{x*100:.2f}%" if isinstance(x, (int, float)) else x
                )
            st.dataframe(pivot_show, use_container_width=True)

            # Vintage折线图
            st.subheader("Vintage 逾期率趋势")
            plot_data = res["vintage_detail"].copy()
            fig = px.line(
                plot_data,
                x="期号",
                y="逾期率",
                color="Vintage",
                markers=True,
                title="各批次账龄逾期率演化曲线"
            )
            fig.update_layout(yaxis_tickformat=".2%")
            st.plotly_chart(fig, use_container_width=True)

        # Tab2: 迁徙率
        with tab2:
            st.subheader("月度迁徙率统计表")
            roll_show = res["roll_rate"].copy()
            # 百分比格式化
            for col in roll_show.columns:
                roll_show[col] = roll_show[col].apply(lambda x: f"{x*100:.2f}%" if isinstance(x, (int, float)) else x)
            st.dataframe(roll_show, use_container_width=True)

            # 迁徙率热力图（近6个月趋势）
            st.subheader("迁徙率热力图（近6个月趋势）")
            roll_heat_data = res["roll_rate"].drop(columns=["近12月平均值"]).iloc[:, -6:]
            fig_heat = px.imshow(
                roll_heat_data,
                text_auto=".2%",
                color_continuous_scale="Reds",
                aspect="auto",
                title="各逾期档位月度迁徙率变化"
            )
            st.plotly_chart(fig_heat, use_container_width=True)

        # Tab3: 损失率与拨备
        with tab3:
            col_left, col_right = st.columns(2)
            with col_left:
                st.subheader("各级损失率")
                loss_show = res["loss_rates"].copy()
                for col in loss_show.columns:
                    loss_show[col] = loss_show[col].apply(lambda x: f"{x*100:.2f}%")
                st.dataframe(loss_show, use_container_width=True)

            with col_right:
                st.subheader("月度拨备汇总")
                prov_show = res["monthly_provision"].copy()
                prov_show["整体拨备率"] = prov_show["整体拨备率"].apply(lambda x: f"{x*100:.2f}%")
                st.dataframe(prov_show, use_container_width=True)

        # Tab4: 明细
        with tab4:
            st.subheader("首次逾期明细")
            st.dataframe(res["first_overdue"], use_container_width=True)

# ========== 4. 风险预警中心 ==========
elif page == "风险预警中心":
    st.header("风险预警中心")

    if "analysis_result" not in st.session_state:
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
            st.dataframe(continuous_df, width='stretch')

            col1, col2, col3 = st.columns(3)
            col1.metric("持续恶化高风险合同数", f"{len(continuous_df)} 户")
            col2.metric("涉及未偿还本金", f"{continuous_df['未偿还本金'].sum():,.2f} 元")
            col3.metric("平均连续恶化期数", f"{continuous_df['连续升档期数'].mean():.1f} 期")

        # Tab2：大额逾期Top榜
        with tab2:
            st.subheader("大额逾期合同Top20")
            top_overdue = df_clean[df_clean["is_overdue"] == 1].drop_duplicates(subset=["合同号"])[
                ["合同号", "客户名称", "逾期天数（DPD）", "未偿还本金"]
            ].sort_values("未偿还本金", ascending=False).head(20)
            st.dataframe(top_overdue, width='stretch')

# ========== 5. AI智能解读 ==========
elif page == "AI智能解读":
    st.header("AI智能资产质量解读")
    st.caption("基于豆包大模型，自动生成专业风控分析报告")

    if "analysis_result" not in st.session_state:
        st.warning("请先在「数据上传清洗」页面上传文件并执行分析")
    else:
        st.success("✅ 已检测到分析数据，点击下方按钮生成AI报告")

        col_btn, col_space = st.columns([1, 3])
        with col_btn:
            generate_btn = st.button("生成AI分析报告", type="primary", use_container_width=True)

        # 点击生成按钮
        if generate_btn:
            with st.spinner("正在调用大模型生成分析报告，约需1-2分钟..."):
                try:
                    report = generate_risk_report(st.session_state["analysis_result"])
                    st.session_state["ai_report"] = report
                except Exception as e:
                    st.error(f"报告生成失败：{str(e)}")

        # 展示报告
        if "ai_report" in st.session_state:
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
                    use_container_width=True
                )