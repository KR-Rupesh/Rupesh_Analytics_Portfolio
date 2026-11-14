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
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        if "gcp_service_account" in st.secrets:
            creds_json = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
            client = gspread.authorize(creds)
        elif os.path.exists("credentials.json"):
            creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
            client = gspread.authorize(creds)
        else:
            st.error("❌ Google Sheets Error: No GCP credentials found in st.secrets!")
            return

        spreadsheet = client.open("Portfolio_User_Submissions")
        sheet = spreadsheet.get_worksheet(0)
        
        headers = [
            "Timestamp", "Selected Stocks", "Quantities", "Lookback Years", "Future Years",
            "MF 1 Name", "MF 1 Amount", "MF 2 Name", "MF 2 Amount",
            "Gold Amount", "FD Amount", "FD Rate",
            "Investor Profile", "Stock Return (%)", "Combined Return (%)", "Total Projected Wealth (₹)"
        ]
        
        existing_records = sheet.get_all_values()
        if not existing_records:
            sheet.append_row(headers)

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ", ".join(data_dict["stocks"]),
            str(data_dict["quantities"]),
            data_dict["lookback_years"],
            data_dict["future_years"],
            data_dict["mf1_name"],
            data_dict["mf1_amount"],
            data_dict["mf2_name"],
            data_dict["mf2_amount"],
            data_dict["gold_amount"],
            data_dict["fd_amount"],
            data_dict["fd_rate"],
            data_dict["auto_investor_type"],
            f"{data_dict['stock_return']:.2f}%",
            f"{data_dict['combined_return']:.2f}%",
            f"{data_dict['projected_wealth']:.2f}"
        ]
        
        sheet.append_row(row)
        st.toast("✅ Submission logged to Google Sheets!", icon="📥")

    except Exception as e:
        st.error(f"⚠️ Google Sheets Logging Failed: {e}")

# 1. Fetch NSE Stocks Tickers (Cached for 24h)
@st.cache_data(ttl=86400, show_spinner=False)
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

# Fetch Mutual Fund List from AMFI (Cached for 24h)
@st.cache_data(ttl=86400, show_spinner=False)
def get_mf_list():
    try:
        res = requests.get("https://api.mfapi.in/mf", timeout=10)
        if res.status_code == 200:
            data = res.json()
            return {item["schemeName"]: item["schemeCode"] for item in data}
    except Exception:
        pass
    return {"HDFC Top 100 Fund - Direct Plan - Growth": 119062}

# Fetch Single Mutual Fund Historical NAV Helper (Cached for 1h)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_mf_nav_pair(mf_code, start_date_obj, default_start_str, default_end_str):
    mf_nav_start, mf_nav_curr = 10.0, 10.0
    mf_start_date, mf_curr_date = default_start_str, default_end_str
    try:
        mf_res = requests.get(f"https://api.mfapi.in/mf/{mf_code}", timeout=10).json()
        nav_data = mf_res.get("data", [])
        if nav_data:
            mf_nav_curr = float(nav_data[0]["nav"])
            mf_curr_date = datetime.strptime(nav_data[0]["date"], "%d-%m-%Y").strftime("%Y-%m-%d")
            
            target_start_dt = start_date_obj.date() if isinstance(start_date_obj, datetime) else start_date_obj
            start_item = nav_data[-1]
            
            for entry in reversed(nav_data):
                entry_dt = datetime.strptime(entry["date"], "%d-%m-%Y").date()
                if entry_dt >= target_start_dt:
                    start_item = entry
                    break
                    
            mf_nav_start = float(start_item["nav"])
            mf_start_date = datetime.strptime(start_item["date"], "%d-%m-%Y").strftime("%Y-%m-%d")
    except Exception:
        pass
    return mf_nav_start, mf_nav_curr, mf_start_date, mf_curr_date

# Sector Fetcher with Robust Exception & Fallback Handling
@st.cache_data(ttl=86400, show_spinner=False)
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
        stock = yf.Ticker(ticker)
        info = stock.info or {}
        sector = info.get("sector")
        if sector:
            return sector
    except Exception:
        pass
    return fallback_map.get(ticker, "Other / Diversified")

# Fetch Last Dividend Info Safely
@st.cache_data(ttl=3600, show_spinner=False)
def get_last_dividend(ticker):
    try:
        divs = yf.Ticker(ticker).dividends
        if not divs.empty:
            last_date = divs.index[-1].strftime("%Y-%m-%d")
            last_val = f"₹{divs.iloc[-1]:.2f}"
            return last_date, last_val
    except Exception:
        pass
    return "N/A", "N/A"

# Batched & Cached Download of Yahoo Finance Data
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_historical_stock_data(tickers, start_str, end_str):
    try:
        stock_data = yf.download(tickers, start=start_str, end=end_str, progress=False)
        close_prices = stock_data['Close'] if 'Close' in stock_data else stock_data
        if isinstance(close_prices, pd.Series):
            close_prices = close_prices.to_frame(name=tickers[0])
        close_prices = close_prices.ffill().bfill()
        return close_prices
    except Exception:
        return pd.DataFrame()

nse_stocks = get_nse_stocks()
mf_dict = get_mf_list()
mf_options = list(mf_dict.keys())

# 2. Sidebar Inputs
st.sidebar.header("1. Portfolio Asset Inputs")

# Stocks Inputs (Default Active - No Toggle)
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

st.sidebar.divider()

# Mutual Fund Section with Toggle (Max 2 Mutual Funds)
st.sidebar.subheader("Mutual Fund Investment (Max 2)")
enable_mf = st.sidebar.toggle("Enable Mutual Fund Calculation", value=False)
selected_mfs = st.sidebar.multiselect(
    "Select Mutual Funds (Max 2)",
    options=mf_options,
    default=[mf_options[0]] if mf_options else [],
    max_selections=2,
    disabled=not enable_mf
)

mf_amounts = {}
if enable_mf and selected_mfs:
    for idx, mf_name in enumerate(selected_mfs, start=1):
        short_label = mf_name[:30] + "..." if len(mf_name) > 30 else mf_name
        mf_amounts[mf_name] = st.sidebar.number_input(
            f"MF {idx} Amount: {short_label} (₹)",
            min_value=0.0,
            value=25000.0,
            step=5000.0,
            key=f"mf_amt_{idx}"
        )

st.sidebar.divider()

# Gold Section with Toggle
st.sidebar.subheader("Gold Investment")
enable_gold = st.sidebar.toggle("Enable Gold Calculation", value=False)
gold_amount = st.sidebar.number_input("Gold Amount (₹)", min_value=0.0, value=50000.0, step=5000.0, disabled=not enable_gold)

st.sidebar.divider()

# Fixed Deposit Section with Toggle
st.sidebar.subheader("Fixed Deposit (FD) Investment")
enable_fd = st.sidebar.toggle("Enable FD Calculation", value=False)
fd_amount = st.sidebar.number_input("FD Amount (₹)", min_value=0.0, value=100000.0, step=5000.0, disabled=not enable_fd)
fd_rate = st.sidebar.number_input("FD Interest Rate (% p.a.)", min_value=0.0, max_value=20.0, value=7.0, step=0.5, disabled=not enable_fd)

st.sidebar.header("2. Timeframes & Benchmarks")
lookback_years = st.sidebar.number_input("Historical Lookback (Years)", min_value=1, max_value=20, value=3)
future_years = st.sidebar.number_input("🔮 Future Projection Horizon (Years)", min_value=1, max_value=30, value=5)

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
        
        with st.spinner("Fetching Yahoo Finance historical & Mutual Fund NAV data..."):
            close_prices = fetch_historical_stock_data(tickers, start_str, end_str)

            nifty_raw = yf.download("^NSEI", start=start_str, end=end_str, progress=False)
            nifty_close = nifty_raw['Close'] if 'Close' in nifty_raw else nifty_raw
            if isinstance(nifty_close, pd.DataFrame):
                nifty_close = nifty_close.iloc[:, 0]
            nifty_close = nifty_close.ffill().bfill()

            # Gold Fetching (Only if toggled ON)
            gold_close = pd.Series(dtype=float)
            if enable_gold:
                gold_raw = yf.download("GOLDBEES.NS", start=start_str, end=end_str, progress=False)
                gold_close = gold_raw['Close'] if 'Close' in gold_raw else gold_raw
                if isinstance(gold_close, pd.DataFrame):
                    gold_close = gold_close.iloc[:, 0]
                gold_close = gold_close.ffill().bfill()

            # Mutual Funds NAV Fetching (Up to 2 MFs)
            mf_results = []
            if enable_mf and selected_mfs:
                for mf_name in selected_mfs:
                    mf_code = mf_dict.get(mf_name)
                    invested_amt = mf_amounts.get(mf_name, 0.0)
                    nav_start, nav_curr, m_start_dt, m_curr_dt = fetch_mf_nav_pair(
                        mf_code, start_date, start_str, end_str
                    )
                    curr_val = (invested_amt / nav_start) * nav_curr if nav_start > 0 else invested_amt
                    ret_pct = ((nav_curr - nav_start) / nav_start) * 100 if nav_start > 0 else 0.0
                    mf_cagr = (((nav_curr / nav_start) ** (1 / lookback_years)) - 1) if nav_start > 0 else 0.0
                    mf_results.append({
                        "name": mf_name,
                        "invested": invested_amt,
                        "curr_val": curr_val,
                        "nav_start": nav_start,
                        "nav_curr": nav_curr,
                        "start_date": m_start_dt,
                        "curr_date": m_curr_dt,
                        "ret_pct": ret_pct,
                        "cagr": mf_cagr
                    })

        if close_prices.empty:
            st.error("Could not load price data for the selected stocks. Please try again.")
        else:
            # Sector Mapping & Master Table Generation
            sector_data = []
            master_rows = []
            portfolio_series = pd.Series(0.0, index=close_prices.index)
            initial_stock_val = 0.0
            current_stock_val = 0.0

            start_dt_str = close_prices.index[0].strftime('%Y-%m-%d')
            curr_dt_str = close_prices.index[-1].strftime('%Y-%m-%d')

            for t in tickers:
                if t in close_prices.columns:
                    prices = close_prices[t]
                    shares = stock_quantities[t]
                    old_p = prices.iloc[0]
                    latest_p = prices.iloc[-1]
                    stk_start_val = old_p * shares
                    stk_curr_val = latest_p * shares
                    stk_ret = ((latest_p - old_p) / old_p) * 100 if old_p > 0 else 0.0
                    
                    portfolio_series += prices * shares
                    initial_stock_val += stk_start_val
                    current_stock_val += stk_curr_val
                    
                    div_date, div_amt = get_last_dividend(t)
                    sector_name = get_stock_sector(t)
                    
                    sector_data.append({
                        "Ticker": t, "Sector": sector_name, "Shares": shares,
                        "Start Val": stk_start_val, "Current Val": stk_curr_val
                    })

                    master_rows.append({
                        "Selected Asset / Stock": t,
                        "Price Taken Date": start_dt_str,
                        "Old Price (₹)": f"₹{old_p:,.2f}",
                        "Latest Date": curr_dt_str,
                        "Latest Price (₹)": f"₹{latest_p:,.2f}",
                        "Returns (%)": f"{stk_ret:+.2f}%",
                        "Invested Amount (as per latest price)": f"₹{stk_curr_val:,.2f}",
                        "Last Dividend Date": div_date,
                        "Last Dividend (₹)": div_amt
                    })

            # Add Mutual Fund rows if toggled ON (Up to 2 MFs)
            total_mf_initial = sum(item["invested"] for item in mf_results)
            total_mf_curr_val = sum(item["curr_val"] for item in mf_results)
            total_mf_fv = sum(item["curr_val"] * ((1 + item["cagr"]) ** future_years) for item in mf_results)

            for item in mf_results:
                master_rows.append({
                    "Selected Asset / Stock": f"MF: {item['name'][:28]}...",
                    "Price Taken Date": item["start_date"],
                    "Old Price (₹)": f"₹{item['nav_start']:,.2f}",
                    "Latest Date": item["curr_date"],
                    "Latest Price (₹)": f"₹{item['nav_curr']:,.2f}",
                    "Returns (%)": f"{item['ret_pct']:+.2f}%",
                    "Invested Amount (as per latest price)": f"₹{item['curr_val']:,.2f}",
                    "Last Dividend Date": "N/A",
                    "Last Dividend (₹)": "N/A"
                })

            # Add Gold row if toggled ON
            gold_curr_val = 0.0
            gold_cagr = 0.0
            if enable_gold and not gold_close.empty:
                gold_start_p = gold_close.iloc[0]
                gold_latest_p = gold_close.iloc[-1]
                gold_curr_val = (gold_amount / gold_start_p) * gold_latest_p if gold_start_p > 0 else gold_amount
                gold_ret = ((gold_latest_p - gold_start_p) / gold_start_p) * 100 if gold_start_p > 0 else 0.0
                gold_cagr = (((gold_latest_p / gold_start_p) ** (1 / lookback_years)) - 1) if gold_start_p > 0 else 0.08
                master_rows.append({
                    "Selected Asset / Stock": "Gold (GOLDBEES)",
                    "Price Taken Date": start_dt_str,
                    "Old Price (₹)": f"₹{gold_start_p:,.2f}",
                    "Latest Date": curr_dt_str,
                    "Latest Price (₹)": f"₹{gold_latest_p:,.2f}",
                    "Returns (%)": f"{gold_ret:+.2f}%",
                    "Invested Amount (as per latest price)": f"₹{gold_curr_val:,.2f}",
                    "Last Dividend Date": "N/A",
                    "Last Dividend (₹)": "N/A"
                })

            # Add FD row if toggled ON
            fd_curr_val = 0.0
            fd_cagr = 0.0
            if enable_fd and fd_amount > 0:
                fd_days = (close_prices.index[-1] - close_prices.index[0]).days
                fd_curr_val = fd_amount * ((1 + (fd_rate / 100 / 365)) ** fd_days)
                fd_ret = ((fd_curr_val - fd_amount) / fd_amount) * 100
                fd_cagr = fd_rate / 100.0
                master_rows.append({
                    "Selected Asset / Stock": f"Fixed Deposit ({fd_rate}% p.a.)",
                    "Price Taken Date": start_dt_str,
                    "Old Price (₹)": f"₹{fd_amount:,.2f}",
                    "Latest Date": curr_dt_str,
                    "Latest Price (₹)": f"₹{fd_curr_val:,.2f}",
                    "Returns (%)": f"{fd_ret:+.2f}%",
                    "Invested Amount (as per latest price)": f"₹{fd_curr_val:,.2f}",
                    "Last Dividend Date": "N/A",
                    "Last Dividend (₹)": "N/A"
                })

            stock_df = pd.DataFrame(sector_data)

            # Totals & Overall Return Calculations
            total_initial_invested = initial_stock_val + (total_mf_initial if enable_mf else 0.0) + (gold_amount if enable_gold else 0.0) + (fd_amount if enable_fd else 0.0)
            total_latest_value = current_stock_val + (total_mf_curr_val if enable_mf else 0.0) + (gold_curr_val if enable_gold else 0.0) + (fd_curr_val if enable_fd else 0.0)
            overall_combined_return_pct = ((total_latest_value - total_initial_invested) / total_initial_invested * 100) if total_initial_invested > 0 else 0.0

            # Latest Weightages for Automated Risk Profiling
            equity_weight_pct = (((current_stock_val + (total_mf_curr_val if enable_mf else 0.0)) / total_latest_value) * 100) if total_latest_value > 0 else 0.0
            gold_weight_pct = ((gold_curr_val / total_latest_value) * 100) if (enable_gold and total_latest_value > 0) else 0.0
            fd_weight_pct = ((fd_curr_val / total_latest_value) * 100) if (enable_fd and total_latest_value > 0) else 0.0

            auto_profile, profile_desc = classify_investor_profile(equity_weight_pct, gold_weight_pct, fd_weight_pct)
            stock_total_return_pct = ((current_stock_val - initial_stock_val) / initial_stock_val) * 100 if initial_stock_val > 0 else 0.0

            daily_pct_change = portfolio_series.pct_change().dropna() * 100
            max_daily_gain = daily_pct_change.max() if not daily_pct_change.empty else 0.0
            max_daily_drop = daily_pct_change.min() if not daily_pct_change.empty else 0.0

            # Wealth Projections
            stock_cagr = (((current_stock_val / initial_stock_val) ** (1 / lookback_years)) - 1) if initial_stock_val > 0 else 0.0
            stock_fv = current_stock_val * ((1 + stock_cagr) ** future_years)
            mf_fv = total_mf_fv if enable_mf else 0.0
            gold_fv = (gold_curr_val * ((1 + gold_cagr) ** future_years)) if enable_gold else 0.0
            fd_fv = (fd_curr_val * ((1 + fd_cagr) ** future_years)) if enable_fd else 0.0
            total_projected_wealth = stock_fv + mf_fv + gold_fv + fd_fv

            portfolio_base100 = (portfolio_series / portfolio_series.iloc[0]) * 100
            nifty_base100 = (nifty_close / nifty_close.iloc[0]) * 100

            # KPIs Section
            st.subheader("📌 Key Historical Indicators")
            kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
            with kpi1:
                st.metric("Stock Starting Capital", f"₹{initial_stock_val:,.2f}")
            with kpi2:
                st.metric("Latest Stock Value", f"₹{current_stock_val:,.2f}")
            with kpi3:
                st.metric("Overall Combined Return", f"{overall_combined_return_pct:+.2f}%")
            with kpi4:
                st.metric("Max Single-Day Gain (Stocks)", f"{max_daily_gain:+.2f}%")
            with kpi5:
                st.metric("Max Single-Day Drop (Stocks)", f"{max_daily_drop:.2f}%")

            st.subheader(f"🔮 Future Value Projections ({future_years}-Year Horizon)")
            fkpi1, fkpi2, fkpi3, fkpi4, fkpi5 = st.columns(5)
            with fkpi1:
                st.metric("Total Projected Wealth", f"₹{total_projected_wealth:,.2f}")
            with fkpi2:
                st.metric("Projected Stock Value", f"₹{stock_fv:,.2f}", f"CAGR: {stock_cagr*100:+.2f}%")
            with fkpi3:
                st.metric("Projected MF Value", f"₹{mf_fv:,.2f}" if enable_mf else "N/A", f"{len(mf_results)} Fund(s)" if enable_mf else "Off")
            with fkpi4:
                st.metric("Projected Gold Value", f"₹{gold_fv:,.2f}" if enable_gold else "N/A", f"CAGR: {gold_cagr*100:+.2f}%" if enable_gold else "Off")
            with fkpi5:
                st.metric("Projected FD Value", f"₹{fd_fv:,.2f}" if enable_fd else "N/A", f"Rate: {fd_rate:.2f}%" if enable_fd else "Off")

            st.divider()

            # Risk Profile Tag
            st.subheader("🏷️ Automated Investor Risk Classification (Based on Latest Weights)")
            prof_col1, prof_col2 = st.columns([1, 1])
            with prof_col1:
                st.success(f"**Detected Risk Profile:** {auto_profile}")
                st.caption(profile_desc)
                st.write(f"• **Equity (Stocks & MFs) Weight:** `{equity_weight_pct:.1f}%`")
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

            # --- ASSET CLASS ALLOCATION PIE CHARTS (STARTING CAP VS LATEST CAP) ---
            pie_header_col, pie_info_col = st.columns([0.9, 0.1])
            with pie_header_col:
                st.subheader("🍰 Asset Class Allocation Drift (Starting Cap vs. Latest Cap)")
            with pie_info_col:
                with st.popover("ℹ️ Info"):
                    st.markdown("""
                    **Asset Class Drift Visualizations:**
                    * **Starting Capital Breakdown:** Shows your initial capital allocation when you entered the positions.
                    * **Latest Capital Breakdown:** Shows how market rallies or drops have shifted your current portfolio weights today.
                    """)

            asset_labels = ["Stock Portfolio"]
            start_asset_values = [initial_stock_val]
            latest_asset_values = [current_stock_val]

            if enable_mf and total_mf_initial > 0:
                asset_labels.append("Mutual Funds")
                start_asset_values.append(total_mf_initial)
                latest_asset_values.append(total_mf_curr_val)
            if enable_gold:
                asset_labels.append("Gold")
                start_asset_values.append(gold_amount)
                latest_asset_values.append(gold_curr_val)
            if enable_fd:
                asset_labels.append("Fixed Deposit (FD)")
                start_asset_values.append(fd_amount)
                latest_asset_values.append(fd_curr_val)

            asset_col1, asset_col2 = st.columns(2)
            with asset_col1:
                st.caption("Asset Class Breakdown — As per Starting Capital")
                start_weights_df = pd.DataFrame({
                    "Asset Class": asset_labels,
                    "Starting Amount (₹)": start_asset_values
                })
                fig_asset_start = px.pie(
                    start_weights_df,
                    values="Starting Amount (₹)",
                    names="Asset Class",
                    hole=0.4
                )
                st.plotly_chart(fig_asset_start, use_container_width=True)

            with asset_col2:
                st.caption("Asset Class Breakdown — As per Latest Capital")
                latest_weights_df = pd.DataFrame({
                    "Asset Class": asset_labels,
                    "Latest Value (₹)": latest_asset_values
                })
                fig_asset_latest = px.pie(
                    latest_weights_df,
                    values="Latest Value (₹)",
                    names="Asset Class",
                    hole=0.4
                )
                st.plotly_chart(fig_asset_latest, use_container_width=True)

            st.divider()

            # --- STOCK SECTOR ALLOCATION PIE CHARTS (STARTING CAP VS LATEST CAP) ---
            sec_header_col, sec_info_col = st.columns([0.9, 0.1])
            with sec_header_col:
                st.subheader("🏭 Stock Portfolio Sector Drift (Starting Cap vs. Latest Cap)")
            with sec_info_col:
                with st.popover("ℹ️ Info"):
                    st.markdown("""
                    **Sector Concentration Drift:**
                    * **Starting Capital Sector Breakdown:** Shows your initial sector exposure.
                    * **Latest Capital Sector Breakdown:** Helps spot over-concentration risk if one sector rallies disproportionately over time.
                    """)

            if not stock_df.empty:
                sec_col1, sec_col2 = st.columns(2)
                with sec_col1:
                    st.caption("Stock Sector Breakdown — As per Starting Capital")
                    sector_start_summary = stock_df.groupby("Sector")["Start Val"].sum().reset_index()
                    fig_sector_start = px.pie(
                        sector_start_summary,
                        values="Start Val",
                        names="Sector",
                        hole=0.4,
                        color_discrete_sequence=px.colors.qualitative.Pastel
                    )
                    st.plotly_chart(fig_sector_start, use_container_width=True)

                with sec_col2:
                    st.caption("Stock Sector Breakdown — As per Latest Capital")
                    sector_latest_summary = stock_df.groupby("Sector")["Current Val"].sum().reset_index()
                    fig_sector_latest = px.pie(
                        sector_latest_summary,
                        values="Current Val",
                        names="Sector",
                        hole=0.4,
                        color_discrete_sequence=px.colors.qualitative.Pastel
                    )
                    st.plotly_chart(fig_sector_latest, use_container_width=True)

            st.divider()

            # --- LINE CHART (WITH INFO ICON) ---
            line_header_col, line_info_col = st.columns([0.9, 0.1])
            with line_header_col:
                st.subheader("📈 Historical Performance (Base = 100)")
            with line_info_col:
                with st.popover("ℹ️ Info"):
                    st.markdown("""
                    **Base 100 Growth Tracking:**
                    * All asset values are normalized to start at **100** on Day 1 of your lookback period.
                    * Allows a direct, side-by-side comparison of return trajectories against the **Nifty 50 Index** benchmark.
                    * Hover over any data point on the lines to view the exact date, index score, and total percentage return.
                    """)

            fig_line = go.Figure()
            
            port_ret = portfolio_base100 - 100
            fig_line.add_trace(go.Scatter(
                x=portfolio_base100.index, 
                y=portfolio_base100, 
                mode='lines', 
                name='My Stock Portfolio',
                hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>Index Value:</b> %{y:.2f}<br><b>Return:</b> %{customdata:+.2f}%<extra></extra>",
                customdata=port_ret
            ))
            
            nifty_ret = nifty_base100 - 100
            fig_line.add_trace(go.Scatter(
                x=nifty_base100.index, 
                y=nifty_base100, 
                mode='lines', 
                name='Nifty 50 Index',
                hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>Index Value:</b> %{y:.2f}<br><b>Return:</b> %{customdata:+.2f}%<extra></extra>",
                customdata=nifty_ret
            ))
            
            if enable_gold and not gold_close.empty:
                gold_base100 = (gold_close / gold_close.iloc[0]) * 100
                gold_ret_series = gold_base100 - 100
                fig_line.add_trace(go.Scatter(
                    x=gold_base100.index, 
                    y=gold_base100, 
                    mode='lines', 
                    name='Gold',
                    hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>Index Value:</b> %{y:.2f}<br><b>Return:</b> %{customdata:+.2f}%<extra></extra>",
                    customdata=gold_ret_series
                ))
            
            if enable_fd:
                days = (close_prices.index - close_prices.index[0]).days
                fd_base100 = 100 * ((1 + (fd_rate / 100 / 365)) ** days)
                fd_ret_series = fd_base100 - 100
                fig_line.add_trace(go.Scatter(
                    x=close_prices.index, 
                    y=fd_base100, 
                    mode='lines', 
                    name=f'FD ({fd_rate}%)', 
                    line=dict(dash='dash'),
                    hovertemplate="<b>Date:</b> %{x|%Y-%m-%d}<br><b>Index Value:</b> %{y:.2f}<br><b>Return:</b> %{customdata:+.2f}%<extra></extra>",
                    customdata=fd_ret_series
                ))
                
            st.plotly_chart(fig_line, use_container_width=True)

            st.divider()

            # --- MASTER TABLE (WITH INFO ICON) ---
            table_header_col, table_info_col = st.columns([0.9, 0.1])
            with table_header_col:
                st.subheader("📋 Comprehensive Portfolio Master Table")
            with table_info_col:
                with st.popover("ℹ️ Info"):
                    st.markdown("""
                    **Master Asset Breakdown:**
                    * Displays starting vs. latest prices, overall return %, and current invested values for all selected stocks, active Mutual Funds, Gold, and FDs.
                    * Includes recent **Dividend Payout History** for equity stock selections.
                    """)

            master_df = pd.DataFrame(master_rows)
            st.dataframe(master_df, use_container_width=True, hide_index=True)

            # Prepare MF 1 & MF 2 fields for Google Sheets logging
            mf1_name = mf_results[0]["name"] if (enable_mf and len(mf_results) >= 1) else "Disabled"
            mf1_amt = mf_results[0]["invested"] if (enable_mf and len(mf_results) >= 1) else 0.0
            mf2_name = mf_results[1]["name"] if (enable_mf and len(mf_results) >= 2) else "None"
            mf2_amt = mf_results[1]["invested"] if (enable_mf and len(mf_results) >= 2) else 0.0

            # Log Data
            save_submission_to_gsheet({
                "stocks": tickers,
                "quantities": stock_quantities,
                "lookback_years": lookback_years,
                "future_years": future_years,
                "mf1_name": mf1_name,
                "mf1_amount": mf1_amt,
                "mf2_name": mf2_name,
                "mf2_amount": mf2_amt,
                "gold_amount": gold_amount if enable_gold else 0.0,
                "fd_amount": fd_amount if enable_fd else 0.0,
                "fd_rate": fd_rate if enable_fd else 0.0,
                "auto_investor_type": auto_profile,
                "stock_return": stock_total_return_pct,
                "combined_return": overall_combined_return_pct,
                "projected_wealth": total_projected_wealth
            })
