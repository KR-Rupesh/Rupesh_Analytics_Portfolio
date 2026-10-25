import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests
import io
import json
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="NSE Portfolio Analyzer", layout="wide")
st.title("📊 NSE Portfolio & Benchmark Performance Analyzer")

# ------------------------------------------------------------------------------
# 1. Fetch Complete List of NSE Listed Stocks
# ------------------------------------------------------------------------------
@st.cache_data(ttl=86400)
def get_nse_stocks():
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            df = pd.read_csv(io.BytesIO(res.content))
            return [f"{row['SYMBOL'].strip()}.NS | {row['NAME OF COMPANY'].strip()}" for _, row in df.iterrows()]
    except Exception:
        pass
    # Fallback list if network request fails
    return [
        "RELIANCE.NS | Reliance Industries Ltd",
        "TCS.NS | Tata Consultancy Services Ltd",
        "INFY.NS | Infosys Ltd",
        "HDFCBANK.NS | HDFC Bank Ltd",
        "ICICIBANK.NS | ICICI Bank Ltd",
        "SBIN.NS | State Bank of India"
    ]

nse_stocks = get_nse_stocks()

# ------------------------------------------------------------------------------
# 2. Sidebar Controls
# ------------------------------------------------------------------------------
st.sidebar.header("1. Stock Selections & Quantities")

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
        stock_quantities[ticker] = st.sidebar.number_input(
            f"Quantity for {ticker}", min_value=1, value=10, step=1
        )

st.sidebar.header("2. Timeframe & Asset Inputs")
lookback_years = st.sidebar.number_input("Analysis Period (Past Years)", min_value=1, max_value=20, value=3)

# Gold Inputs
st.sidebar.subheader("Gold Investment")
gold_amount = st.sidebar.number_input("Gold Invested Amount (₹)", min_value=0.0, value=50000.0, step=5000.0)

# FD Inputs
st.sidebar.subheader("Fixed Deposit (FD) Investment")
fd_amount = st.sidebar.number_input("FD Invested Amount (₹)", min_value=0.0, value=100000.0, step=5000.0)
fd_rate = st.sidebar.number_input("FD Interest Rate (% p.a.)", min_value=0.0, max_value=20.0, value=7.0, step=0.5)

# Investor Profile Input
st.sidebar.header("3. Investor Classification")
investor_type = st.sidebar.selectbox(
    "Investor Profile Persona",
    ["Conservative", "Moderate", "Aggressive", "Growth Focused", "Capital Preservation"]
)

# ------------------------------------------------------------------------------
# 3. Save User Submission to Google Sheets
# ------------------------------------------------------------------------------
def save_submission_to_gsheet(data_dict):
    try:
        # Load credentials securely from Streamlit Secrets
        if "gcp_service_account" in st.secrets:
            creds_json = dict(st.secrets["gcp_service_account"])
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
            client = gspread.authorize(credentials)
            
            # Open Sheet by name
            sheet = client.open("Portfolio_User_Submissions").sheet1
            
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ", ".join(data_dict["stocks"]),
                str(data_dict["quantities"]),
                data_dict["years"],
                data_dict["gold_amount"],
                data_dict["fd_amount"],
                data_dict["fd_rate"],
                data_dict["investor_type"],
                f"{data_dict['stock_return']:.2f}%"
            ]
            sheet.append_row(row)
            st.toast("✅ Submission successfully saved to Google Sheets!", icon="📥")
    except Exception as e:
        # Silence error gracefully if secrets or sheets are not connected yet
        pass

# ------------------------------------------------------------------------------
# 4. Calculation & Visual Dashboard Engine
# ------------------------------------------------------------------------------
if st.sidebar.button("Analyze & Run Portfolio"):
    if not selected_stocks:
        st.warning("Please select at least one stock to analyze.")
    else:
        tickers = list(stock_quantities.keys())
        end_date = datetime.now()
        start_date = end_date - timedelta(days=int(lookback_years * 365))
        
        # Download Stock Historical Data via yfinance
        with st.spinner("Fetching daily market prices from Yahoo Finance..."):
            raw_data = yf.download(
                tickers, 
                start=start_date.strftime('%Y-%m-%d'), 
                end=end_date.strftime('%Y-%m-%d'),
                progress=False
            )['Close']

        if raw_data.empty:
            st.error("Unable to download stock data for the selected timeframe.")
        else:
            if isinstance(raw_data, pd.Series):
                raw_data = raw_data.to_frame(name=tickers[0])

            # Daily Stock Portfolio Values
            portfolio_series = pd.Series(0.0, index=raw_data.index)
            initial_stock_val = 0.0
            current_stock_val = 0.0

            for t in tickers:
                prices = raw_data[t].dropna()
                shares = stock_quantities[t]
                portfolio_series += prices * shares
                initial_stock_val += prices.iloc[0] * shares
                current_stock_val += prices.iloc[-1] * shares

            total_initial_invested = initial_stock_val + gold_amount + fd_amount
            stock_total_return_pct = ((current_stock_val - initial_stock_val) / initial_stock_val) * 100

            # Daily Portfolio Percentage Return for Single-Day Gain / Drop KPIs
            daily_pct_change = portfolio_series.pct_change().dropna() * 100
            max_daily_gain = daily_pct_change.max() if not daily_pct_change.empty else 0.0
            max_daily_drop = daily_pct_change.min() if not daily_pct_change.empty else 0.0

            # Base 100 Curves
            # 1. Stock Portfolio Base 100
            portfolio_base100 = (portfolio_series / portfolio_series.iloc[0]) * 100

            # 2. Benchmark 1: Nifty 50 Index (^NSEI) Base 100
            nifty_data = yf.download(
                "^NSEI", 
                start=start_date.strftime('%Y-%m-%d'), 
                end=end_date.strftime('%Y-%m-%d'),
                progress=False
            )['Close']

            if not nifty_data.empty:
                nifty_series = nifty_data.squeeze()
                nifty_base100 = (nifty_series / nifty_series.iloc[0]) * 100
            else:
                nifty_base100 = pd.Series(100.0, index=raw_data.index)

            # 3. Benchmark 2: Gold ETF Proxy (GOLDBEES) Base 100
            gold_data = yf.download(
                "GOLDBEES.NS", 
                start=start_date.strftime('%Y-%m-%d'), 
                end=end_date.strftime('%Y-%m-%d'),
                progress=False
            )['Close']

            if not gold_data.empty:
                gold_series = gold_data.squeeze()
                gold_base100 = (gold_series / gold_series.iloc[0]) * 100
            else:
                gold_base100 = pd.Series(100.0, index=raw_data.index)

            # 4. Benchmark 3: Fixed Deposit (FD) Compounded Daily Base 100
            days = (raw_data.index - raw_data.index[0]).days
            fd_base100 = 100 * ((1 + (fd_rate / 100 / 365)) ** days)

            # --- VISUAL SECTION 1: KPIs & Persona ---
            st.subheader("Key Portfolio Indicators")
            kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
            
            with kpi_col1:
                st.metric("Total Capital Invested", f"₹{total_initial_invested:,.2f}")
            with kpi_col2:
                st.metric("Stock Return (%)", f"{stock_total_return_pct:+.2f}%")
            with kpi_col3:
                st.metric("Max Single-Day Gain", f"{max_daily_gain:+.2f}%")
            with kpi_col4:
                st.metric("Max Single-Day Drop", f"{max_daily_drop:.2f}%")

            # --- VISUAL SECTION 2: Weights Pie Chart & Profile ---
            col1, col2 = st.columns([1, 1])

            with col1:
                st.subheader("Asset Allocation Weights")
                weights_df = pd.DataFrame({
                    "Asset Class": ["Stock Portfolio", "Gold", "Fixed Deposit (FD)"],
                    "Invested Amount (₹)": [initial_stock_val, gold_amount, fd_amount]
                })
                fig_pie = px.pie(
                    weights_df, 
                    values="Invested Amount (₹)", 
                    names="Asset Class", 
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Pastel
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            with col2:
                st.subheader("Investor Profile Details")
                st.info(f"**Classification Persona:** {investor_type}")
                st.write(f"**Analysis Window:** Past {lookback_years} Years")
                st.write(f"**Total Stock Portfolio Starting Value:** ₹{initial_stock_val:,.2f}")
                st.write(f"**Total Stock Portfolio Latest Value:** ₹{current_stock_val:,.2f}")

            # --- VISUAL SECTION 3: Base 100 Line Chart ---
            st.subheader("Normalized Historical Performance (Base = 100)")
            fig_line = go.Figure()
            
            fig_line.add_trace(go.Scatter(
                x=portfolio_base100.index, y=portfolio_base100, mode='lines', name='My Stock Portfolio', line=dict(width=2.5)
            ))
            fig_line.add_trace(go.Scatter(
                x=nifty_base100.index, y=nifty_base100, mode='lines', name='Nifty 50 Index (^NSEI)', line=dict(width=2.0)
            ))
            fig_line.add_trace(go.Scatter(
                x=gold_base100.index, y=gold_base100, mode='lines', name='Gold (GOLDBEES)', line=dict(width=2.0)
            ))
            fig_line.add_trace(go.Scatter(
                x=raw_data.index, y=fd_base100, mode='lines', name=f'FD ({fd_rate}% p.a.)', line=dict(width=2.0, dash='dash')
            ))

            fig_line.update_layout(
                xaxis_title="Date",
                yaxis_title="Normalized Performance (Base = 100)",
                hovermode="x unified",
                template="plotly_white",
                margin=dict(l=20, r=20, t=30, b=20)
            )
            st.plotly_chart(fig_line, use_container_width=True)

            # --- VISUAL SECTION 4: Summary Table & CSV Download ---
            st.subheader("Selected Holdings Table")
            summary_rows = []
            for t in tickers:
                prices = raw_data[t].dropna()
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

            # Download CSV Button
            csv_bytes = summary_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Portfolio Summary CSV", 
                data=csv_bytes, 
                file_name="portfolio_summary.csv", 
                mime="text/csv"
            )

            # Save data row to Google Sheets database automatically
            save_submission_to_gsheet({
                "stocks": tickers,
                "quantities": stock_quantities,
                "years": lookback_years,
                "gold_amount": gold_amount,
                "fd_amount": fd_amount,
                "fd_rate": fd_rate,
                "investor_type": investor_type,
                "stock_return": stock_total_return_pct
            })
