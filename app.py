import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

st.set_page_config(page_title="🧾 Payment Advice Parser v4.3", layout="wide")
st.title("📄 Payment Advice PDF Parser v4.3")

uploaded_pdf = st.file_uploader("Upload your Payment Advice PDF", type=["pdf"])

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

if uploaded_pdf:
    data = []
    tds_map_signed = {}  # keep signed values for math
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
                    if i+1 < len(lines):
                        date_tokens = lines[i+1].split()
                        if len(date_tokens) >= 2 and is_date(date_tokens[0]) and is_date(date_tokens[1]):
                            inv_date = date_tokens[1]
                            i += 1
                    debit_val = 0.0
                    if i+1 < len(lines) and "Short payment" in lines[i+1]:
                        debit_val = extract_debit(lines[i+1])
                        i += 1
                    key = (inv_no, pay_amt, status)
                    if key not in seen_entries:
                        data.append({
                            'Invoice Number': inv_no,
                            'Invoice Date': inv_date,
                            'Invoice Amount': inv_amt,
                            'GST Adjustment': 0.0,
                            'Payment Amount': pay_amt,
                            'TDS_Signed': 0.0,     # keep signed in raw data
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
                    if i+1 < len(lines):
                        date_tokens = lines[i+1].split()
                        if len(date_tokens) >= 2 and is_date(date_tokens[0]) and is_date(date_tokens[1]):
                            inv_date = date_tokens[1]
                            i += 1
                    key = (inv_no, pay_amt, status)
                    if key not in seen_entries:
                        data.append({
                            'Invoice Number': inv_no,
                            'Invoice Date': inv_date,
                            'Invoice Amount': 0.0,
                            'GST Adjustment': pay_amt,  # signed GST adjustment
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
        'TDS_Signed': 'max',      # signed TDS for math if needed later
        'Debit Note': 'sum',
        'Invoice Date': 'first'
    })

    # Final paid amount (unchanged): Payment + GST adjustments
    pivot_df['Final Paid Amount'] = pivot_df['Payment Amount'] + pivot_df['GST Adjustment']

    # Display TDS as absolute value ONLY in the summary output
    pivot_df['TDS'] = pivot_df['TDS_Signed'].abs()

    # Final column order (with TDS positive)
    pivot_df = pivot_df[[
        'Invoice Number', 'Final Paid Amount', 'TDS',
        'Invoice Amount', 'GST Adjustment', 'Payment Amount', 'Debit Note', 'Invoice Date'
    ]]

    st.success("✅ Final Invoice Summary")
    st.dataframe(pivot_df)

    # Excel: Summary shows TDS without sign; Raw Data keeps TDS_Signed for audit
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pivot_df.to_excel(writer, sheet_name='Final Summary', index=False)
        df_all.to_excel(writer, sheet_name='Raw Data', index=False)
    output.seek(0)

    st.download_button(
        label="📥 Download Excel",
        data=output,
        file_name="invoice_summary_v4_3.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
