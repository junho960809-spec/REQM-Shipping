create table if not exists public.ecount_sales_rawdata (
  id bigint generated always as identity primary key,
  row_key text not null unique,
  sale_date date not null,
  sale_year integer not null,
  sale_month integer not null check (sale_month between 1 and 12),
  sale_day integer not null check (sale_day between 1 and 31),
  weekday text not null default '',
  week_label text not null default '',
  period_label text not null default '',
  category text not null default '',
  customer_code text not null default '',
  customer_name text not null default '',
  item_code text not null,
  item_name text not null default '',
  quantity numeric(18,4) not null default 0,
  supply_amount bigint not null default 0,
  tax_amount bigint not null default 0,
  total_amount bigint not null default 0,
  source text not null default 'ecount',
  synced_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index if not exists ecount_sales_rawdata_date_idx on public.ecount_sales_rawdata (sale_date);
create index if not exists ecount_sales_rawdata_month_item_idx on public.ecount_sales_rawdata (sale_year, sale_month, item_code);
create index if not exists ecount_sales_rawdata_customer_date_idx on public.ecount_sales_rawdata (customer_code, sale_date);

create table if not exists public.ecount_sales_sync_history (
  id uuid primary key default gen_random_uuid(),
  start_date date not null,
  end_date date not null,
  status text not null,
  row_count integer not null default 0,
  quantity_total numeric(18,4) not null default 0,
  supply_total bigint not null default 0,
  error_message text,
  synced_by uuid references auth.users(id),
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

alter table public.ecount_sales_rawdata enable row level security;
alter table public.ecount_sales_sync_history enable row level security;

drop policy if exists "authenticated users read ecount sales" on public.ecount_sales_rawdata;
create policy "authenticated users read ecount sales" on public.ecount_sales_rawdata for select to authenticated using (true);
drop policy if exists "authenticated users write ecount sales" on public.ecount_sales_rawdata;
create policy "authenticated users write ecount sales" on public.ecount_sales_rawdata for all to authenticated using (true) with check (true);
drop policy if exists "authenticated users read sync history" on public.ecount_sales_sync_history;
create policy "authenticated users read sync history" on public.ecount_sales_sync_history for select to authenticated using (true);
drop policy if exists "authenticated users write sync history" on public.ecount_sales_sync_history;
create policy "authenticated users write sync history" on public.ecount_sales_sync_history for insert to authenticated with check (synced_by = auth.uid());

create or replace function public.ecount_monthly_item_sales(p_months jsonb)
returns table(item_code text, sale_year integer, sale_month integer, quantity numeric)
language sql stable security invoker
as $$
  select r.item_code, r.sale_year, r.sale_month, sum(r.quantity)
  from public.ecount_sales_rawdata r
  join jsonb_to_recordset(p_months) as m(year integer, month integer)
    on r.sale_year = m.year and r.sale_month = m.month
  group by r.item_code, r.sale_year, r.sale_month;
$$;

create or replace function public.replace_ecount_sales_period(p_start_date date, p_end_date date, p_rows jsonb)
returns jsonb
language plpgsql security invoker
as $$
declare
  inserted_count integer;
  quantity_sum numeric;
  supply_sum bigint;
begin
  if p_start_date > p_end_date then
    raise exception '시작일이 종료일보다 늦습니다.';
  end if;
  if exists (
    select 1 from jsonb_to_recordset(p_rows) as x(sale_date date)
    where x.sale_date < p_start_date or x.sale_date > p_end_date
  ) then
    raise exception '조회 기간 밖의 판매자료가 포함되어 있습니다.';
  end if;

  delete from public.ecount_sales_rawdata where sale_date between p_start_date and p_end_date;
  insert into public.ecount_sales_rawdata (
    row_key,sale_date,sale_year,sale_month,sale_day,weekday,week_label,period_label,category,
    customer_code,customer_name,item_code,item_name,quantity,supply_amount,tax_amount,total_amount,source,synced_at
  )
  select row_key,sale_date,sale_year,sale_month,sale_day,coalesce(weekday,''),coalesce(week_label,''),
    coalesce(period_label,''),coalesce(category,''),coalesce(customer_code,''),coalesce(customer_name,''),
    item_code,coalesce(item_name,''),coalesce(quantity,0),coalesce(supply_amount,0),coalesce(tax_amount,0),
    coalesce(total_amount,0),coalesce(source,'ecount'),coalesce(synced_at,now())
  from jsonb_to_recordset(p_rows) as x(
    row_key text,sale_date date,sale_year integer,sale_month integer,sale_day integer,weekday text,
    week_label text,period_label text,category text,customer_code text,customer_name text,item_code text,
    item_name text,quantity numeric,supply_amount bigint,tax_amount bigint,total_amount bigint,source text,synced_at timestamptz
  );
  get diagnostics inserted_count = row_count;
  select coalesce(sum(quantity),0), coalesce(sum(supply_amount),0) into quantity_sum, supply_sum
    from public.ecount_sales_rawdata where sale_date between p_start_date and p_end_date;
  insert into public.ecount_sales_sync_history(start_date,end_date,status,row_count,quantity_total,supply_total,synced_by,completed_at)
    values(p_start_date,p_end_date,'success',inserted_count,quantity_sum,supply_sum,auth.uid(),now());
  return jsonb_build_object('row_count',inserted_count,'quantity_total',quantity_sum,'supply_total',supply_sum);
end;
$$;

grant execute on function public.ecount_monthly_item_sales(jsonb) to authenticated;
grant execute on function public.replace_ecount_sales_period(date,date,jsonb) to authenticated;
