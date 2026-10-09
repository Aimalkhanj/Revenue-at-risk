# LinkedIn post (paste as text, attach the dashboard image or a carousel)

A retailer grew sales by 1.7% last year.
Behind that number, it lost 1 in 3 of its customers.

I analysed 1 million transactions from a UK online gift wholesaler (UCI Online Retail II) to answer one question: why do customers stop buying, and what is it costing the business?

What the data showed:

📉 Growth was fragile. Orders fell 4%. All the growth came from bigger baskets, not more customers.

🔁 1,519 customers (35.8%) never came back, taking £1.05M of annual revenue with them. 1,585 new customers replaced them. Net gain: 66.

⏳ Only about 1 in 5 new customers buys again in the following month. The second order is where loyalty is won or lost.

🚨 601 repeat customers are overdue right now, silent for more than twice their usual reorder gap. Together they are worth £601K a year.

🎯 The first order predicts loyalty. Customers with a large first order reorder 84% of the time vs 65% for small first orders (χ² p < 0.001).

What I'd do first:
1️⃣ Win back overdue customers with a weekly overdue list → +£150K
2️⃣ Engineer the second order within 30 days → +£84K
3️⃣ Fix the most-returned products → +£22K

Total: £255K, which is 1.6× the company's entire growth for the year.

How I built it:
• SQL (DuckDB) for the data model: orders fact table, customer dimension, cohort retention
• Python for cleaning, RFM segmentation, CLV, chi-square testing and market basket analysis
• A single-frame dashboard designed for an executive to read in 10 seconds

Every cleaning rule, assumption and line of code is in the repo 👇
[GitHub link]

What would you test first: the win-back campaign or the second-order offer?

#DataAnalytics #BusinessAnalytics #SQL #Python #CustomerAnalytics #DataVisualization #Retail #CustomerRetention

---

## Carousel outline (8 slides)

1. **Hook:** "Sales grew 1.7%. They lost 1 in 3 customers."
2. **The question:** Why do customers stop buying, and what does it cost?
3. **The data:** 1,067,371 lines · 5,852 customers · 43 countries · Dec 2009–Dec 2011 · SQL + Python
4. **Insight 1:** Growth came from bigger baskets, not more orders (monthly chart)
5. **Insight 2:** Only 20% of new customers come back (cohort heatmap)
6. **Insight 3:** £601K sits with 601 overdue customers (KPI card + segment panel)
7. **The plan:** three actions, £255K, 1.6× this year's growth
8. **The dashboard** + link to repo and live dashboard
