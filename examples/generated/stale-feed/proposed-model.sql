-- Singular dbt test: fail when the newest exchange rate is more than two days old.
select
    max(cast(rate_date as date)) as latest_rate_date,
    date_diff('day', max(cast(rate_date as date)), current_date) as stale_days
from {{ ref('exchange_rates') }}
having max(cast(rate_date as date)) < current_date - interval 2 day
