# Coupon Source Audit (2026-11-23)
Public, one-time, **read-only** checks of 238 discovery leads, 113 documentary entries, 15 Phase-4 additions, and 119 coupon source pages. 485 rows including duplicates; deduplicated URL fetches.

This verifies **HTTP reachability only**, readable RSS/JSON shape where available, coupon presence in public source page text, and stored expiry dates. It does NOT sign in, redeem codes, add products to cart, place orders, assert live checkout validity, test merchant permissions, or circumvent rate limits. A reachable documentation page is not a functioning authenticated coupon API.

Run the audit from GitHub Actions. Download CSV results from the artifact attached to the workflow run. Individual sources may block datacenter IPs or require login. A 403 response is *not proof of a dead provider*. Ethical, limited, read-only probes; max 350 KB per URL; 1.3s minimum between requests on each hostname. All data sources are public research URLs. License and commercial reuse must be vetted separately.
