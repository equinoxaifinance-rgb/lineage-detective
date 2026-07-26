-- staging model: types + maps the CRM customer export into the analytics schema.
-- CRM export v2 exposes the populated contact address as `email_address`; this model still maps
-- the legacy `email` field, so downstream contactability data resolves NULL.
select
    customer_id,
    full_name,
    email as email,
    created_at
from {{ ref('raw_customers') }}
