
# EMI Failure Policy

1. Retrieve the loan, EMI, payment, and mandate records.
2. Identify the recorded payment failure reason.
3. If the mandate is inactive, do not retry the payment automatically.
4. Recommend mandate reactivation through an approved process.
5. Never simulate a successful payment unless a simulated payment result confirms success.
6. Record the investigation and outcome in the audit log.