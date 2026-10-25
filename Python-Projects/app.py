import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests
import io

st.set_page_config(page_title="NSE Portfolio Analyzer", layout="wide")
st.title("📊 NSE Portfolio & Benchmark Performance Analyzer")

# 1. Fetch official list of NSE stocks
@st.cache_data(ttl=86400)
def get_nse_stocks():
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            df = pd.read_csv(io.BytesIO(res.content))
            return [f"{row['SYMBOL'].strip()}.NS | {row['NAME OF COMPANY'].strip()}" for _, row in df.iterrows()]
    except Exception:
        pass
    return [
        "RELIANCE.NS | Reliance Industries Ltd",
        "TCS.NS | Tata Consultancy Services Ltd",
        "INFY.NS | Infosys Ltd",
        "HDFCBANK.NS | HDFC Bank Ltd"
    ]

nse_stocks = get_nse_stocks()

# 2. Sidebar Controls
st.sidebar.header("1. Portfolio Stocks & Shares")
selected_stocks = st.sidebar.multiselect(
    "Select NSE Stocks (Max 10)",
    options=nse_stocks,
    default=[nse_stocks[0]],
    max_selections=10
)

stock_quantities = {}
if selected_stocks:
    st.sidebar.subheader("Stock Quantities")
    for stock in selected_stocks:
        ticker = stock.split(" | ")[0]
        stock_quantities[ticker] = st.sidebar.number_input(f"Shares for {ticker}", min_value=1, value=10, step=1)

st.sidebar.header("2. Benchmark & Timeframe Inputs")
lookback_years = st.sidebar.number_input("Analysis Period (Years)", min_value=1, max_value=20, value=3)

st.sidebar.subheader("Gold Investment")
gold_amount = st.sidebar.number_input("Gold Amount (₹)", min_value=0.0, value=50000.0, step=5000.0)

st.sidebar.subheader("Fixed Deposit (FD) Investment")
fd_amount = st.sidebar.number_input("FD Amount (₹)", min_value=0.0, value=100000.0, step=5000.0)
fd_rate = st.sidebar.number_input("FD Interest Rate (% p.a.)", min_value=0.0, max_value=20.0, value=7.0, step=0.5)

st.sidebar.header("3. Investor Classification")
investor_type = st.sidebar.selectbox("Investor Persona", ["Conservative", "Moderate", "Aggressive", "Growth Focused"])

# 3. Calculation & Dashboard Execution
if st.sidebar.button("Analyze & Run Portfolio"):
    if not selected_stocks:
        st.warning("Please select at least one stock to analyze.")
    else:
        tickers = list(stock_quantities.keys())
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(lookback_years * 365))
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        with st.spinner("Downloading daily historical data from Yahoo Finance..."):
            # Download Selected Stock Data
            stock_data = yf.download(tickers, start=start_str, end=end_str, progress=False)
            
            # Format Data safely regardless of single or multi-ticker output
            if 'Close' in stock_data:
                close_prices = stock_data['Close']
            else:
                close_prices = stock_data

            if isinstance(close_prices, pd.Series):
                close_prices = close_prices.to_frame(name=tickers[0])

            close_prices = close_prices.ffill().bfill()

            # Download Nifty 50 Benchmark (^NSEI)
            nifty_raw = yf.download("^NSEI", start=start_str, end=end_str, progress=False)
            nifty_close = nifty_raw['Close'] if 'Close' in nifty_raw else nifty_raw
            if isinstance(nifty_close, pd.DataFrame):
                nifty_close = nifty_close.iloc[:, 0]
            nifty_close = nifty_close.ffill().bfill()

            # Download Gold Benchmark Proxy (GOLDBEES.NS)
            gold_raw = yf.download("GOLDBEES.NS", start=start_str, end=end_str, progress=False)
            gold_close = gold_raw['Close'] if 'Close' in gold_raw else gold_raw
            if isinstance(gold_close, pd.DataFrame):
                gold_close = gold_close.iloc[:, 0]
            gold_close = gold_close.ffill().bfill()

        # Calculate Total Daily Portfolio Value
        portfolio_series = pd.Series(0.0, index=close_prices.index)
        initial_stock_val = 0.0
        current_stock_val = 0.0

        for t in tickers:
            if t in close_prices.columns:
                prices = close_prices[t]
                shares = stock_quantities[t]
                portfolio_series += prices * shares
                initial_stock_val += prices.iloc[0] * shares
                current_stock_val += prices.iloc[-1] * shares

        total_initial_invested = initial_stock_val + gold_amount + fd_amount
        stock_total_return_pct = ((current_stock_val - initial_stock_val) / initial_stock_val) * 100 if initial_stock_val > 0 else 0.0

        # Calculate Daily Percentage Changes for Max Gain / Drop KPIs
        daily_pct_change = portfolio_series.pct_change().dropna() * 100
        max_daily_gain = daily_pct_change.max() if not daily_pct_change.empty else 0.0
        max_daily_drop = daily_pct_change.min() if not daily_pct_change.empty else 0.0

        # Base 100 Normalization Curves
        # 1. Stock Portfolio Base 100
        portfolio_base100 = (portfolio_series / portfolio_series.iloc[0]) * 100

        # 2. Nifty 50 Base 100
        nifty_base100 = (nifty_close / nifty_close.iloc[0]) * 100

        # 3. Gold Base 100
        if not gold_close.empty and len(gold_close) > 0:
            gold_base100 = (gold_close / gold_close.iloc[0]) * 100
        else:
            gold_base100 = pd.Series(100.0, index=close_prices.index)

        # 4. FD Daily Compounded Base 100
        days = (close_prices.index - close_prices.index[0]).days
        fd_base100 = 100 * ((1 + (fd_rate / 100 / 365)) ** days)

        # --- SECTION 1: KPI CARDS ---
        st.subheader("📌 Key Performance Indicators (KPIs)")
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
        with kpi1:
            st.metric("Total Starting Capital", f"₹{total_initial_invested:,.2f}")
        with kpi2:
            st.metric("Stock Portfolio Return", f"{stock_total_return_pct:+.2f}%")
        with kpi3:
            st.metric("Max Single-Day Gain", f"{max_daily_gain:+.2f}%")
        with kpi4:
            st.metric("Max Single-Day Drop", f"{max_daily_drop:.2f}%")

        st.divider()

        # --- SECTION 2: ASSET ALLOCATION & PROFILE ---
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("Asset Allocation Breakdown")
            weights_df = pd.DataFrame({
                "Asset Class": ["Stock Portfolio", "Gold", "Fixed Deposit (FD)"],
                "Invested Amount (₹)": [initial_stock_val, gold_amount, fd_amount]
            })
            fig_pie = px.pie(
                weights_df, 
                values="Invested Amount (₹)", 
                names="Asset Class", 
                hole=0.4,
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with col2:
            st.subheader("Investor Profile Details")
            st.info(f"**Classification Persona:** {investor_type}")
            st.write(f"**Time Horizon:** Past {lookback_years} Years")
            st.write(f"**Initial Stock Portfolio Value:** ₹{initial_stock_val:,.2f}")
            st.write(f"**Current Stock Portfolio Value:** ₹{current_stock_val:,.2f}")
            st.write(f"**Gold Capital Allocation:** ₹{gold_amount:,.2f}")
            st.write(f"**Fixed Deposit Allocation:** ₹{fd_amount:,.2f} @ {fd_rate}% p.a.")

        st.divider()

        # --- SECTION 3: BASE-100 COMPARISON CHART ---
        st.subheader("📈 Normalized Historical Performance (Base = 100)")
        fig_line = go.Figure()
        
        # Add 4 Traces: Stocks, Nifty 50, Gold, FD
        fig_line.add_trace(go.Scatter(
            x=portfolio_base100.index, y=portfolio_base100, mode='lines', name='My Stock Portfolio', line=dict(width=3, color='#1f77b4')
        ))
        fig_line.add_trace(go.Scatter(
            x=nifty_base100.index, y=nifty_base100, mode='lines', name='Nifty 50 Index (^NSEI)', line=dict(width=2, color='#ff7f0e')
        ))
        fig_line.add_trace(go.Scatter(
            x=gold_base100.index, y=gold_base100, mode='lines', name='Gold (GOLDBEES)', line=dict(width=2, color='#ffd700')
        ))
        fig_line.add_trace(go.Scatter(
            x=close_prices.index, y=fd_base100, mode='lines', name=f'FD ({fd_rate}% p.a.)', line=dict(width=2, color='#2ca02c', dash='dash')
        ))

        fig_line.update_layout(
            xaxis_title="Date",
            yaxis_title="Normalized Value (Base = 100)",
            hovermode="x unified",
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_line, use_container_width=True)

        # --- SECTION 4: HOLDINGS SUMMARY & CSV EXPORT ---
        st.subheader("📋 Selected Stock Holdings Summary")
        summary_rows = []
        for t in tickers:
            if t in close_prices.columns:
                prices = close_prices[t]
                start_p = prices.iloc[0]
                end_p = prices.iloc[-1]
                qty = stock_quantities[t]
                summary_rows.append({
                    "Ticker": t,
                    "Quantity": qty,
                    "Start Price (₹)": round(start_p, 2),
                    "Latest Price (₹)": round(end_p, 2),
                    "Initial Value (₹)": round(start_p * qty, 2),
                    "Current Value (₹)": round(end_p * qty, 2),
                    "Return (%)": round(((end_p - start_p) / start_p) * 100, 2)
                })

        summary_df = pd.DataFrame(summary_rows)
        st.dataframe(summary_df, use_container_width=True)

        csv_bytes = summary_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Portfolio Summary CSV", 
            data=csv_bytes, 
            file_name="portfolio_summary.csv", 
            mime="text/csv"
        )
