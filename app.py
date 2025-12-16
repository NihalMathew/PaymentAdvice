import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

st.set_page_config(page_title="🧾 VCC Payment Advice Parser v4.3", layout="wide")
st.title("📄 VCC Payment Advice PDF Parser v4.4")

uploaded_pdf = st.file_uploader("Upload your Payment Advice PDF", type=["pdf"])

# ✅ Account validation config (Page 1 only)
EXPECTED_ACCT = "30305409"
ACCT_REGEX = re.compile(r"Your\s*A/c\s*with\s*us\s*:\s*(\d+)", re.IGNORECASE)

def validate_account_number_page1(pdf_file, expected_acct: str) -> bool:
    """
    Checks ONLY page 1 for 'Your A/c with us : <number>'.
    Returns True if expected account number is found, else False.
    """
    try:
        pdf_file.seek(0)
        with pdfplumber.open(pdf_file) as pdf:
            if len(pdf.pages) == 0:
                return False
            text = (pdf.pages[0].extract_text() or "")
            m = ACCT_REGEX.search(text)
            if not m:
                return False
            found = m.group(1).strip()
            return found == expected_acct
    except Exception:
        return False
    finally:
        try:
            pdf_file.seek(0)
        except Exception:
            pass

def parse_signed_number(x):
    match = re.search(r'-?\d+(?:,\d{3})*(?:\.\d{1,2})?-?', str(x))
    if match:
        num_str = match.group(0).replace(',', '')
        if num_str.endswith('-') and not num_str.startswith('-'):
            num_str = '-' + num_str[:-1]
        return float(num_str)
    return 0.0

def is_invoice_no(s):
    return bool(re.match(r'^(R\d+|VCC[-/]?\w+)', s, re.IGNORECASE))

def is_date(s):
    return bool(re.match(r'\d{2}\.\d{2}\.\d{4}', s))

def extract_debit(line):
    match = re.search(r'Rs\.?([\d,]+\.\d{1,2})', line)
    return float(match.group(1).replace(',', '')) if match else 0.0

def read_table(file):
    """
    Load CSV or Excel into a DataFrame with trimmed column names.
    """
    if file is None:
        return None
    try:
        df = pd.read_excel(file)
    except Exception:
        file.seek(0)
        df = pd.read_csv(file)
    df.columns = [str(c).strip() for c in df.columns]
    return df

def normalize_invoice(s):
    return str(s).upper().strip().replace(' ', '')

def normalize_state(s):
    return re.sub(r'\s+', ' ', str(s).upper().strip())

if uploaded_pdf:
    # ✅ Gatekeeper check BEFORE any parsing (Page 1 only)
    if not validate_account_number_page1(uploaded_pdf, EXPECTED_ACCT):
        st.error(
            f"❌ Invalid Payment Advice file.\n\n"
            f"This tool only accepts PDFs with 'Your A/c with us : {EXPECTED_ACCT}' on page 1."
        )
        st.stop()

    data = []
    tds_map_signed = {}
    seen_entries = set()
    last_invoice = None

    with pdfplumber.open(uploaded_pdf) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = text.split("\n")
            i = 0
            while i < len(lines):
                tokens = lines[i].split()

                # Main invoice entry
                if len(tokens) >= 4 and is_invoice_no(tokens[1]):
                    doc_no, inv_no = tokens[0], tokens[1]
                    inv_amt = parse_signed_number(tokens[2])
                    pay_amt = parse_signed_number(tokens[3])
                    status = "MAIN ENTRY"
                    inv_date = ""
                    if i + 1 < len(lines):
                        date_tokens = lines[i + 1].split()
                        if len(date_tokens) >= 2 and is_date(date_tokens[0]) and is_date(date_tokens[1]):
                            inv_date = date_tokens[1]
                            i += 1
                    debit_val = 0.0
                    if i + 1 < len(lines) and "Short payment" in lines[i + 1]:
                        debit_val = extract_debit(lines[i + 1])
                        i += 1

                    key = (inv_no, pay_amt, status)
                    if key not in seen_entries:
                        data.append({
                            'Invoice Number': inv_no,
                            'Invoice Date': inv_date,
                            'Invoice Amount': inv_amt,
                            'GST Adjustment': 0.0,
                            'Payment Amount': pay_amt,
                            'TDS_Signed': 0.0,
                            'Debit Note': debit_val,
                            'Status': status
                        })
                        seen_entries.add(key)
                    last_invoice = inv_no

                # GST entry (paid/hold)
                elif len(tokens) >= 3 and is_invoice_no(tokens[1]):
                    doc_no, inv_no = tokens[0], tokens[1]
                    pay_amt = parse_signed_number(tokens[2])
                    status = "GST PAID" if pay_amt > 0 else "GST HOLD"
                    inv_date = ""
                    if i + 1 < len(lines):
                        date_tokens = lines[i + 1].split()
                        if len(date_tokens) >= 2 and is_date(date_tokens[0]) and is_date(date_tokens[1]):
                            inv_date = date_tokens[1]
                            i += 1

                    key = (inv_no, pay_amt, status)
                    if key not in seen_entries:
                        data.append({
                            'Invoice Number': inv_no,
                            'Invoice Date': inv_date,
                            'Invoice Amount': 0.0,
                            'GST Adjustment': pay_amt,
                            'Payment Amount': 0.0,
                            'TDS_Signed': 0.0,
                            'Debit Note': 0.0,
                            'Status': status
                        })
                        seen_entries.add(key)
                    last_invoice = inv_no

                # TDS line (capture signed value, once per invoice)
                if "TDS Amount" in lines[i] and last_invoice:
                    if last_invoice not in tds_map_signed:
                        nums = [parse_signed_number(n) for n in lines[i].split() if re.search(r'\d', n)]
                        if nums:
                            tds_map_signed[last_invoice] = nums[0]

                i += 1

    # Build DataFrame
    df_all = pd.DataFrame(data)

    # Map signed TDS to every row of that invoice for raw view
    df_all['TDS_Signed'] = df_all['Invoice Number'].map(tds_map_signed).fillna(0.0)

    # Aggregate to summary
    pivot_df = df_all.groupby(['Invoice Number'], as_index=False).agg({
        'Invoice Amount': 'max',
        'GST Adjustment': 'sum',
        'Payment Amount': 'sum',
        'TDS_Signed': 'max',
        'Debit Note': 'sum',
        'Invoice Date': 'first'
    })

    # Final paid amount: Payment + GST adjustments
    pivot_df['Final Paid Amount'] = pivot_df['Payment Amount'] + pivot_df['GST Adjustment']

    # Display TDS as absolute value ONLY in the summary output
    pivot_df['TDS'] = pivot_df['TDS_Signed'].abs()

    # Reorder (base, without Import Name yet)
    base_cols = [
        'Invoice Number', 'Final Paid Amount', 'TDS',
        'Invoice Amount', 'GST Adjustment', 'Payment Amount', 'Debit Note', 'Invoice Date'
    ]
    pivot_df = pivot_df[base_cols].copy()

    st.success("✅ Final Invoice Summary")
    st.dataframe(pivot_df)

    # ============== Optional Import Name enrichment ==============
    st.markdown("---")
    st.subheader("Optional: Add Import Name (via Ledger & State mapping)")
    want_import = st.checkbox("Add 'Import Name' column using E-Invoice Ledger and State Details?")

    enriched_df = pivot_df.copy()

    if want_import:
        ledger_file = st.file_uploader(
            "Upload E-Invoice Ledger Report (must include 'Invoice Number' and 'Ship To (State)')",
            type=["xlsx", "xls", "csv"], key="ledger"
        )
        state_map_file = st.file_uploader(
            "Upload State Details (must include 'STATE NAME' and 'IMPORT NAME')",
            type=["xlsx", "xls", "csv"], key="state"
        )

        if ledger_file and state_map_file:
            ledger_df = read_table(ledger_file)
            state_df = read_table(state_map_file)

            ledger_required = {'Invoice Number', 'Ship To (State)'}
            state_required = {'STATE NAME', 'IMPORT NAME'}
            missing_ledger = ledger_required - set(ledger_df.columns)
            missing_state = state_required - set(state_df.columns)

            if missing_ledger:
                st.error(f"Ledger file is missing columns: {missing_ledger}")
            elif missing_state:
                st.error(f"State Details file is missing columns: {missing_state}")
            else:
                ledger_df = ledger_df.copy()
                ledger_df['__INV_JOIN__'] = ledger_df['Invoice Number'].map(normalize_invoice)
                ledger_df['__STATE_JOIN__'] = ledger_df['Ship To (State)'].map(normalize_state)

                state_df = state_df.copy()
                state_df['__STATE_JOIN__'] = state_df['STATE NAME'].map(normalize_state)
                state_df = state_df[['__STATE_JOIN__', 'IMPORT NAME']].drop_duplicates()

                enriched_df = enriched_df.copy()
                enriched_df['__INV_JOIN__'] = enriched_df['Invoice Number'].map(normalize_invoice)

                tmp = pd.merge(
                    enriched_df,
                    ledger_df[['__INV_JOIN__', '__STATE_JOIN__']].drop_duplicates(),
                    on='__INV_JOIN__',
                    how='left'
                )

                tmp = pd.merge(
                    tmp,
                    state_df,
                    on='__STATE_JOIN__',
                    how='left'
                )

                tmp.rename(columns={'IMPORT NAME': 'Import Name'}, inplace=True)
                tmp.drop(columns=['__INV_JOIN__', '__STATE_JOIN__'], inplace=True)

                cols_with_import = ['Invoice Number', 'Import Name'] + [c for c in base_cols if c != 'Invoice Number']
                cols_with_import = [c for i, c in enumerate(cols_with_import) if c not in cols_with_import[:i]]
                enriched_df = tmp[cols_with_import]

                matched = enriched_df['Import Name'].notna().sum()
                total = len(enriched_df)
                st.info(f"Matched Import Name for {matched} of {total} invoices.")
                st.success("✅ Final Invoice Summary (with Import Name)")
                st.dataframe(enriched_df)

    # ============================ Export ============================
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        (enriched_df if want_import and 'Import Name' in enriched_df.columns else pivot_df)\
            .to_excel(writer, sheet_name='Final Summary', index=False)
        df_all.to_excel(writer, sheet_name='Raw Data', index=False)
    output.seek(0)

    st.download_button(
        label="📥 Download Excel",
        data=output,
        file_name="invoice_summary_v4_3.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
