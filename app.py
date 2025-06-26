# 📌 Install dependencies
!pip install pdfplumber openpyxl pandas

import pdfplumber
import pandas as pd
import re
from google.colab import drive
import os

# 📌 Mount Google Drive
drive.mount('/content/drive')

# 📌 Define input and output paths
pdf_path = '/content/drive/My Drive/VCC/Invoice.pdf'
output_dir = '/content/drive/My Drive/VCC/OutputPmt'
os.makedirs(output_dir, exist_ok=True)
output_file = os.path.join(output_dir, 'invoice_summary.xlsx')

# 📌 Initialize data list
data = []

# 📌 Parse PDF
with pdfplumber.open(pdf_path) as pdf:
    for page in pdf.pages:
        text = page.extract_text()

        # Match lines with invoice/payment info
        # Now capturing Inv./Ref. Doc.No (R number) + Inv./Ref. Doc.Date
        pattern = re.compile(
            r'(\d{8})\s+(R\d+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+'
            r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})'
        )

        # Match TDS
        tds_pattern = re.compile(r'TDS Amount\s+([\d\.\-]+)')

        tds_values = tds_pattern.findall(text)
        matches = pattern.findall(text)

        tds_index = 0
        for match in matches:
            doc_no, inv_ref_no, inv_amt, pay_amt, doc_date, inv_ref_date = match

            # Clean numeric strings
            inv_amt = float(inv_amt.replace(',', ''))
            pay_amt = float(pay_amt.replace(',', ''))

            # Get TDS value
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

# 📌 Build DataFrame
df = pd.DataFrame(data)

# 📌 Aggregate by Invoice Number (Inv./Ref No) and Inv./Ref Date
pivot_df = df.groupby(
    ['Invoice Number', 'Invoice Date', 'Invoice Amount'],
    as_index=False
).agg({
    'Payment Amount': 'sum',
    'TDS': 'sum'
})

# 📌 Save to Excel
pivot_df.to_excel(output_file, index=False)

print(f"✅ Excel saved at: {output_file}")

