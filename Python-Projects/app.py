import time
import subprocess

# 1. Clear old processes & install dependencies
!pkill -f streamlit
!pkill -f cloudflared
!pip install -q streamlit yfinance plotly pandas requests gspread google-auth

# 2. Download Cloudflare tunnel binary
!wget -q -c https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
!chmod +x cloudflared

# 3. Create the complete app.py script
app_code = """
import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests
import io
import os
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="NSE Portfolio Analyzer", layout="wide")
st.title("📊 Portfolio, Sector & Automated Risk Profiler")

# --- Google Sheets Integration ---
def save_submission_to_gsheet(data_dict):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        if os.path.exists("credentials.json"):
            creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
            client = gspread.authorize(creds)
        elif "gcp_service_account" in st.secrets:
            creds_json = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
            client = gspread.authorize(creds)
        else:
            return

        sheet = client.open("Portfolio_User_Submissions").sheet1
        
        headers = [
            "Timestamp", "Selected Stocks", "Quantities", "Years", 
            "Gold Amount", "FD Amount", "FD Rate", "Investor Profile", "Portfolio Return (%)"
        ]
        
        existing_records = sheet.get_all_values()
        if not existing_records:
            sheet.append_row(headers)

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ", ".join(data_dict["stocks"]),
            str(data_dict["quantities"]),
            data_dict["years"],
            data_dict["gold_amount"],
            data_dict["fd_amount"],
            data_dict["fd_rate"],
            data_dict["auto_investor_type"],
            f"{data_dict['stock_return']:.2f}%"
        ]
        sheet.append_row(row)
        st.toast("✅ Submission logged to Google Sheets!", icon="📥")
    except Exception:
        pass

# 1. Fetch NSE Stocks Tickers
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

# Sector Fetcher with Fallback Mapping
@st.cache_data(ttl=86400)
def get_stock_sector(ticker):
    fallback_map = {
        "RELIANCE.NS": "Energy / Conglomerate",
        "TCS.NS": "Information Technology",
        "INFY.NS": "Information Technology",
        "HDFCBANK.NS": "Financial Services",
        "ICICIBANK.NS": "Financial Services",
        "SBIN.NS": "Financial Services",
        "BHARTIARTL.NS": "Telecommunications",
        "ITC.NS": "Consumer Goods (FMCG)",
        "LT.NS": "Construction & Engineering"
    }
    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector")
        if sector:
            return sector
    except Exception:
        pass
    return fallback_map.get(ticker, "Other / Diversified")

nse_stocks = get_nse_stocks()

# 2. Sidebar Inputs
st.sidebar.header("1. Portfolio Asset Inputs")
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

st.sidebar.header("2. Timeframes & Benchmarks")
lookback_years = st.sidebar.number_input("Historical Lookback (Years)", min_value=1, max_value=20, value=3)
future_years = st.sidebar.number_input("🔮 Future Projection Horizon (Years)", min_value=1, max_value=30, value=5)

st.sidebar.subheader("Gold Investment")
gold_amount = st.sidebar.number_input("Gold Amount (₹)", min_value=0.0, value=50000.0, step=5000.0)

st.sidebar.subheader("Fixed Deposit (FD) Investment")
fd_amount = st.sidebar.number_input("FD Amount (₹)", min_value=0.0, value=100000.0, step=5000.0)
fd_rate = st.sidebar.number_input("FD Interest Rate (% p.a.)", min_value=0.0, max_value=20.0, value=7.0, step=0.5)

def classify_investor_profile(equity_pct, gold_pct, fd_pct):
    if equity_pct <= 40 and fd_pct >= 10:
        return "Conservative", "🛡️ High capital preservation focus with balanced FD/Gold protection."
    elif 40 < equity_pct <= 65:
        return "Moderate (Balanced)", "⚖️ Growth balanced with lower volatility asset classes."
    elif 65 < equity_pct <= 85:
        return "Aggressive", "🚀 High growth focus with strong capital exposure to equities."
    else:
        return "Very Aggressive / Speculative", "🔥 Maximum capital appreciation focus with extreme equity weight."

# 3. Execution & Calculations
if st.sidebar.button("Analyze & Run Portfolio"):
    if not selected_stocks:
        st.warning("Please select at least one stock to analyze.")
    else:
        tickers = list(stock_quantities.keys())
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(lookback_years * 365))
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        
        with st.spinner("Fetching Yahoo Finance historical & sector data..."):
            stock_data = yf.download(tickers, start=start_str, end=end_str, progress=False)
            close_prices = stock_data['Close'] if 'Close' in stock_data else stock_data
            if isinstance(close_prices, pd.Series):
                close_prices = close_prices.to_frame(name=tickers[0])
            close_prices = close_prices.ffill().bfill()

            nifty_raw = yf.download("^NSEI", start=start_str, end=end_str, progress=False)
            nifty_close = nifty_raw['Close'] if 'Close' in nifty_raw else nifty_raw
            if isinstance(nifty_close, pd.DataFrame):
                nifty_close = nifty_close.iloc[:, 0]
            nifty_close = nifty_close.ffill().bfill()

            gold_raw = yf.download("GOLDBEES.NS", start=start_str, end=end_str, progress=False)
            gold_close = gold_raw['Close'] if 'Close' in gold_raw else gold_raw
            if isinstance(gold_close, pd.DataFrame):
                gold_close = gold_close.iloc[:, 0]
            gold_close = gold_close.ffill().bfill()

        # Sector Mapping & Performance Tracking
        sector_data = []
        portfolio_series = pd.Series(0.0, index=close_prices.index)
        initial_stock_val = 0.0
        current_stock_val = 0.0

        for t in tickers:
            if t in close_prices.columns:
                prices = close_prices[t]
                shares = stock_quantities[t]
                stk_start_val = prices.iloc[0] * shares
                stk_curr_val = prices.iloc[-1] * shares
                
                portfolio_series += prices * shares
                initial_stock_val += stk_start_val
                current_stock_val += stk_curr_val
                
                sector_name = get_stock_sector(t)
                sector_data.append({
                    "Ticker": t,
                    "Sector": sector_name,
                    "Shares": shares,
                    "Start Val": stk_start_val,
                    "Current Val": stk_curr_val
                })

        stock_df = pd.DataFrame(sector_data)

        total_initial_invested = initial_stock_val + gold_amount + fd_amount
        equity_weight_pct = (initial_stock_val / total_initial_invested * 100) if total_initial_invested > 0 else 0
        gold_weight_pct = (gold_amount / total_initial_invested * 100) if total_initial_invested > 0 else 0
        fd_weight_pct = (fd_amount / total_initial_invested * 100) if total_initial_invested > 0 else 0

        auto_profile, profile_desc = classify_investor_profile(equity_weight_pct, gold_weight_pct, fd_weight_pct)
        stock_total_return_pct = ((current_stock_val - initial_stock_val) / initial_stock_val) * 100 if initial_stock_val > 0 else 0.0

        daily_pct_change = portfolio_series.pct_change().dropna() * 100
        max_daily_gain = daily_pct_change.max() if not daily_pct_change.empty else 0.0
        max_daily_drop = daily_pct_change.min() if not daily_pct_change.empty else 0.0

        stock_cagr = (((current_stock_val / initial_stock_val) ** (1 / lookback_years)) - 1) if initial_stock_val > 0 else 0.0
        gold_cagr = (((gold_close.iloc[-1] / gold_close.iloc[0]) ** (1 / lookback_years)) - 1) if not gold_close.empty and gold_close.iloc[0] > 0 else 0.08
        fd_cagr = fd_rate / 100.0

        stock_fv = current_stock_val * ((1 + stock_cagr) ** future_years)
        gold_fv = gold_amount * ((1 + gold_cagr) ** future_years)
        fd_fv = fd_amount * ((1 + fd_cagr) ** future_years)
        total_projected_wealth = stock_fv + gold_fv + fd_fv

        portfolio_base100 = (portfolio_series / portfolio_series.iloc[0]) * 100
        nifty_base100 = (nifty_close / nifty_close.iloc[0]) * 100
        gold_base100 = (gold_close / gold_close.iloc[0]) * 100 if not gold_close.empty else pd.Series(100.0, index=close_prices.index)
        days = (close_prices.index - close_prices.index[0]).days
        fd_base100 = 100 * ((1 + (fd_rate / 100 / 365)) ** days)

        # KPIs
        st.subheader("📌 Key Historical Indicators")
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        with kpi1:
            st.metric("Total Starting Capital", f"₹{total_initial_invested:,.2f}")
        with kpi2:
            st.metric("Stock Portfolio Return", f"{stock_total_return_pct:+.2f}%")
        with kpi3:
            st.metric("Max Single-Day Gain", f"{max_daily_gain:+.2f}%")
        with kpi4:
            st.metric("Max Single-Day Drop", f"{max_daily_drop:.2f}%")

        st.subheader(f"🔮 Future Value Projections ({future_years}-Year Horizon)")
        fkpi1, fkpi2, fkpi3, fkpi4 = st.columns(4)
        with fkpi1:
            st.metric("Total Projected Wealth", f"₹{total_projected_wealth:,.2f}")
        with fkpi2:
            st.metric("Projected Stock Value", f"₹{stock_fv:,.2f}", f"CAGR: {stock_cagr*100:+.2f}%")
        with fkpi3:
            st.metric("Projected Gold Value", f"₹{gold_fv:,.2f}", f"CAGR: {gold_cagr*100:+.2f}%")
        with fkpi4:
            st.metric("Projected FD Value", f"₹{fd_fv:,.2f}", f"Rate: {fd_rate:.2f}%")

        st.divider()

        # Risk Profile Tag
        st.subheader("🏷️ Automated Investor Risk Classification")
        prof_col1, prof_col2 = st.columns([1, 1])
        with prof_col1:
            st.success(f"**Detected Risk Profile:** {auto_profile}")
            st.caption(profile_desc)
            st.write(f"• **Equity (Stocks) Weight:** `{equity_weight_pct:.1f}%`")
            st.write(f"• **Gold / Alternatives Weight:** `{gold_weight_pct:.1f}%`")
            st.write(f"• **Fixed Deposit (FD) Weight:** `{fd_weight_pct:.1f}%`")

        with prof_col2:
            st.subheader("Reference Benchmark Allocation Matrix")
            matrix_df = pd.DataFrame([
                {"Risk Profile": "Conservative", "Equity": "20–40%", "Debt / FD": "10–15%", "Gold": "10–20%"},
                {"Risk Profile": "Moderate (Balanced)", "Equity": "50–65%", "Debt / FD": "5–10%", "Gold": "10–15%"},
                {"Risk Profile": "Aggressive", "Equity": "70–85%", "Debt / FD": "0–5%", "Gold": "5–10%"},
                {"Risk Profile": "Very Aggressive / Speculative", "Equity": "90–95%", "Debt / FD": "0%", "Gold": "0–5%"}
            ])
            st.dataframe(matrix_df, use_container_width=True, hide_index=True)

        st.divider()

        # --- SECTOR & ASSET ALLOCATION PIE CHARTS ---
        st.subheader("🍰 Asset Class & Sector Allocation Pie Charts")
        pie_col1, pie_col2 = st.columns(2)
        
        with pie_col1:
            st.subheader("Asset Class Breakdown")
            weights_df = pd.DataFrame({
                "Asset Class": ["Stock Portfolio", "Gold", "Fixed Deposit (FD)"],
                "Invested Amount (₹)": [initial_stock_val, gold_amount, fd_amount]
            })
            fig_asset_pie = px.pie(weights_df, values="Invested Amount (₹)", names="Asset Class", hole=0.4)
            st.plotly_chart(fig_asset_pie, use_container_width=True)

        with pie_col2:
            st.subheader("Stock Portfolio Sector Breakdown")
            if not stock_df.empty:
                sector_summary = stock_df.groupby("Sector")["Current Val"].sum().reset_index()
                fig_sector_pie = px.pie(
                    sector_summary, 
                    values="Current Val", 
                    names="Sector", 
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                st.plotly_chart(fig_sector_pie, use_container_width=True)

        st.divider()

        # Line Chart
        st.subheader("📈 Historical Performance (Base = 100)")
        fig_line = go.Figure()
        fig_line.add_trace(go.Scatter(x=portfolio_base100.index, y=portfolio_base100, mode='lines', name='My Stock Portfolio'))
        fig_line.add_trace(go.Scatter(x=nifty_base100.index, y=nifty_base100, mode='lines', name='Nifty 50 Index'))
        fig_line.add_trace(go.Scatter(x=gold_base100.index, y=gold_base100, mode='lines', name='Gold'))
        fig_line.add_trace(go.Scatter(x=close_prices.index, y=fd_base100, mode='lines', name=f'FD ({fd_rate}%)', line=dict(dash='dash')))
        st.plotly_chart(fig_line, use_container_width=True)

        st.divider()

        # --- SECTOR CONTRIBUTION TABLE ---
        st.subheader("📊 Sector-Wise Performance & Contribution Summary")
        if not stock_df.empty:
            sector_table = stock_df.groupby("Sector").agg(
                Initial_Capital=("Start Val", "sum"),
                Current_Value=("Current Val", "sum"),
                Stock_Count=("Ticker", "count")
            ).reset_index()
            
            sector_table["Return (%)"] = ((sector_table["Current_Value"] - sector_table["Initial_Capital"]) / sector_table["Initial_Capital"]) * 100
            sector_table["Portfolio Contribution (%)"] = (sector_table["Current_Value"] / current_stock_val) * 100 if current_stock_val > 0 else 0
            
            sector_table["Initial Capital (₹)"] = sector_table["Initial_Capital"].apply(lambda x: f"₹{x:,.2f}")
            sector_table["Current Value (₹)"] = sector_table["Current_Value"].apply(lambda x: f"₹{x:,.2f}")
            sector_table["Return (%)"] = sector_table["Return (%)"].apply(lambda x: f"{x:+.2f}%")
            sector_table["Sector Share (%)"] = sector_table["Portfolio Contribution (%)"].apply(lambda x: f"{x:.1f}%")
            
            st.dataframe(
                sector_table[["Sector", "Stock_Count", "Initial Capital (₹)", "Current Value (₹)", "Return (%)", "Sector Share (%)"]],
                use_container_width=True,
                hide_index=True
            )

        # Log Data
        save_submission_to_gsheet({
            "stocks": tickers,
            "quantities": stock_quantities,
            "years": lookback_years,
            "gold_amount": gold_amount,
            "fd_amount": fd_amount,
            "fd_rate": fd_rate,
            "auto_investor_type": auto_profile,
            "stock_return": stock_total_return_pct
        })
"""

with open("app.py", "w") as f:
    f.write(app_code)

# 4. Launch Streamlit server on 127.0.0.1:8501
print("Starting Streamlit process...")
subprocess.Popen(["streamlit", "run", "app.py", "--server.address", "127.0.0.1", "--server.port", "8501"])

# Wait 5 seconds for server to start
time.sleep(5)

# 5. Connect Cloudflare Tunnel
print("Launching Cloudflare Tunnel... Copy the link below to test in Incognito mode:")
!./cloudflared tunnel --url http://127.0.0.1:8501
