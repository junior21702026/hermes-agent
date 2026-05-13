Input: extraction JSON plus 1-3 factual claims.
Output: JSON array of {claim, supported: bool, source_url, note}.
Use researcher model only when score >= 8 and claims are present. If no researcher client is available, log a stub verification result instead of blocking routing.
