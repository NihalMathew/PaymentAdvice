import streamlit as st
import pdfplumber
import pandas as pd
import re
from io import BytesIO

st.set_page_config(page_title="🧾 Payment Advice Parser", layout="wide")
st.title("📄 Payment Advice PDF Parser")

uploaded_pdf = st.file_uploader("Upload your Payment Advice PDF", type=["pdf"])

if uploaded_pdf:
    data = []

    with pdfplumber.open(uploaded_pdf) as pdf:
        for page in pdf.pages:
            text = page.extract_text()

            # Match lines with invoice/payment info
            pattern = re.compile(
                r'(\d{8})\s+(R\d+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+'
                r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})'
            )
            tds_pattern = re.compile(r'TDS Amount\s+([\d\.\-]+)')
            tds_values = tds_pattern.findall(text)
            matches = pattern.findall(text)

            tds_index = 0
            for match in matches:
                doc_no, inv_ref_no, inv_amt, pay_amt, doc_date, inv_ref_date = match

                inv_amt = float(inv_amt.replace(',', ''))
                pay_amt = float(pay_amt.replace(',', ''))

                tds = 0.0
                if tds_index < len(tds_values):
                    try:
                        tds_raw = tds_values[tds_index].replace('-', '').strip()
                        tds = float(tds_raw)
                    except:
                        tds = 0.0
                    tds_index += 1

                data.append({
                    'Invoice Number': inv_ref_no,
                    'Invoice Date': inv_ref_date,
                    'Invoice Amount': inv_amt,
                    'Payment Amount': pay_amt,
                    'TDS': tds
                })

    if not data:
        st.warning("No invoice data found in the PDF.")
    else:
        df = pd.DataFrame(data)

        pivot_df = df.groupby(
            ['Invoice Number', 'Invoice Date', 'Invoice Amount'],
            as_index=False
        ).agg({
            'Payment Amount': 'sum',
            'TDS': 'sum'
        })

        st.success("✅ Extracted invoice summary:")
        st.dataframe(pivot_df)

        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pivot_df.to_excel(writer, index=False, sheet_name="Invoice Summary")
        output.seek(0)

        st.download_button(
            label="📥 Download Excel",
            data=output,
            file_name="invoice_summary.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
