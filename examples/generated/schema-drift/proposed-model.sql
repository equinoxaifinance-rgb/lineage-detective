select
    customer_id,
    full_name,
    email_address as email,
    created_at
from {{ ref('raw_customers') }}
