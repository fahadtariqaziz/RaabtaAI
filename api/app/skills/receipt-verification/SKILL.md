Reading Pakistani payment receipts (bank deposit slips, 1Link/Raast transfers, JazzCash, Easypaisa).

Fields to extract: amount (PKR), date/time, channel (bank name / JazzCash / Easypaisa / Raast / 1Link IBFT), transaction or reference id (TID, STAN, RRN, slip number), payer name or account/wallet (masked), payee (institution account/title or voucher number), student name/roll/challan number if printed.

Common formats:
- Bank challan/voucher: institution copy/bank copy, challan number, bank stamp and teller signature, due date and "payable after due date" amount.
- JazzCash/Easypaisa screenshots: green/red app screen, "Transaction successful", TID (11–12 digits), date/time, amount, receiver name.
- Raast/IBFT: sender and receiver bank, IBAN fragments, reference number.

Red flags (report, don't accuse): edited or misaligned digits, mismatched fonts, missing reference id, amount differs from expected, date before the bill date or in the future, payee is not the institution, cropped screenshot hiding fields, duplicate reference already submitted.

Output confidence low when the image is blurry or partial. Never mark a payment as confirmed — staff confirm.
