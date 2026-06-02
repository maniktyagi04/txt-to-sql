# Phase 4: SQL Generation Testing Report

This report documents the verification of 20 distinct, realistic SQL queries across sales, marketing, and support database domains, checking formatting syntax, join paths, filters, and aggregations against the mock SQLite database.

---

## 1. Batch Test Cases & Validation Results

| ID | Test Question | SQL Syntax | Validation | Execution | Row Count | Latency |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Show total sales orders in the West region. | `SELECT COUNT(*) FROM analytics.sales_orders WHERE region = 'West';` | **PASSED** | **PASSED** | 1 | 2.77ms |
| 2 | Get customer names in the West region. | `SELECT account_name FROM analytics.customers WHERE region = 'West';` | **PASSED** | **PASSED** | 2 | 0.24ms |
| 3 | List campaigns with conversions > 100. | `SELECT campaign_name, conversions FROM marketing.campaign_performance WHERE conversions > 100;` | **PASSED** | **PASSED** | 3 | 0.22ms |
| 4 | Clicks and impressions by channel. | `SELECT channel, SUM(clicks) as total_clicks, SUM(impressions) as total_impressions FROM marketing.campaign_performance GROUP BY channel;` | **PASSED** | **PASSED** | 4 | 0.29ms |
| 5 | Average CSAT score for support tickets. | `SELECT AVG(csat_score) FROM support.tickets;` | **PASSED** | **PASSED** | 1 | 0.23ms |
| 6 | Top 5 customers by sales amount. | `SELECT customer_id, SUM(enterprise_sales_amount) as total_sales FROM analytics.sales_orders GROUP BY customer_id ORDER BY total_sales DESC LIMIT 5;` | **PASSED** | **PASSED** | 4 | 0.25ms |
| 7 | High priority unresolved support tickets. | `SELECT ticket_id, status FROM support.tickets WHERE priority = 'High' AND status != 'Resolved';` | **PASSED** | **PASSED** | 1 | 0.23ms |
| 8 | Sales & discount in West region. | `SELECT enterprise_sales_amount, discount_amount FROM analytics.sales_orders WHERE region = 'West';` | **PASSED** | **PASSED** | 3 | 0.29ms |
| 9 | Active products in 'Cloud Services'. | `SELECT product_name, sku FROM analytics.products WHERE is_active = 1 AND category = 'Cloud Services';` | **PASSED** | **PASSED** | 0 | 0.42ms |
| 10 | Sales orders count grouped by status. | `SELECT order_status, COUNT(*) FROM analytics.sales_orders GROUP BY order_status;` | **PASSED** | **PASSED** | 4 | 0.22ms |
| 11 | Marketing spend for email channel. | `SELECT SUM(spend) FROM marketing.campaign_performance WHERE channel = 'Email';` | **PASSED** | **PASSED** | 1 | 0.22ms |
| 12 | Customers with open support tickets. | `SELECT c.account_name, t.ticket_id FROM analytics.customers c JOIN support.tickets t ON c.customer_id = t.customer_id WHERE t.status != 'Resolved';` | **PASSED** | **PASSED** | 2 | 0.22ms |
| 13 | Campaigns with conversions and clicks. | `SELECT campaign_name, conversions, clicks FROM marketing.campaign_performance WHERE conversions > 0 AND clicks > 0;` | **PASSED** | **PASSED** | 4 | 0.21ms |
| 14 | Customer name and order date for orders. | `SELECT c.account_name, o.order_date FROM analytics.sales_orders o JOIN analytics.customers c ON o.customer_id = c.customer_id;` | **PASSED** | **PASSED** | 6 | 0.22ms |
| 15 | Active products that have been sold. | `SELECT DISTINCT p.product_name FROM analytics.sales_orders o JOIN analytics.products p ON o.product_id = p.product_id WHERE p.is_active = 1;` | **PASSED** | **PASSED** | 3 | 0.25ms |
| 16 | Sales and discount by customer segment. | `SELECT c.segment, SUM(o.enterprise_sales_amount) as sales, AVG(o.discount_amount) as discount FROM analytics.sales_orders o JOIN analytics.customers c ON o.customer_id = c.customer_id GROUP BY c.segment;` | **PASSED** | **PASSED** | 3 | 0.26ms |
| 17 | Unresolved tickets with CSAT. | `SELECT ticket_id, csat_score FROM support.tickets WHERE status != 'Resolved';` | **PASSED** | **PASSED** | 2 | 0.20ms |
| 18 | Campaign conversions by start date. | `SELECT start_date, SUM(conversions) FROM marketing.campaign_performance GROUP BY start_date;` | **PASSED** | **PASSED** | 4 | 0.22ms |
| 19 | Orders placed on calendar holidays. | `SELECT o.order_id, o.order_date FROM analytics.sales_orders o JOIN analytics.calendar c ON o.order_date = c.date_day WHERE c.is_holiday = 1;` | **PASSED** | **PASSED** | 1 | 0.31ms |
| 20 | Customer segments and total orders count. | `SELECT c.segment, COUNT(o.order_id) FROM analytics.sales_orders o JOIN analytics.customers c ON o.customer_id = c.customer_id GROUP BY c.segment;` | **PASSED** | **PASSED** | 3 | 0.22ms |

---

## 2. Technical Findings

- **Syntax & Semantics**: The generated queries follow valid SQLite dialect guidelines. All table structures (`analytics.*`, `support.*`, `marketing.*`) are matched correctly.
- **Join Resolution**: Multi-table joins (e.g. joining `sales_orders` with `customers` on `customer_id`) are correctly handled and resolved by SQLGlot and SQLite.
- **Latency Performance**: Average query execution latency on the SQLite engine is exceptionally fast, averaging **~0.3ms per query** with no errors or engine lockups.
