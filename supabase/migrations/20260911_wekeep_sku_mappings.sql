create table if not exists public.wekeep_sku_mappings (
  item_code text primary key,
  wekeep_manage_code text not null default '',
  product_name text not null default '',
  sku_no text,
  customer_barcode text not null default '',
  is_active boolean not null default true,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id)
);

create unique index if not exists wekeep_sku_mappings_active_sku_idx
  on public.wekeep_sku_mappings (sku_no)
  where is_active and sku_no is not null and btrim(sku_no) <> '';

create index if not exists wekeep_sku_mappings_active_item_idx
  on public.wekeep_sku_mappings (is_active, item_code);

alter table public.wekeep_sku_mappings enable row level security;

drop policy if exists "authenticated users read wekeep sku mappings"
  on public.wekeep_sku_mappings;
create policy "authenticated users read wekeep sku mappings"
  on public.wekeep_sku_mappings for select to authenticated using (true);

drop policy if exists "admins write wekeep sku mappings"
  on public.wekeep_sku_mappings;
create policy "admins write wekeep sku mappings"
  on public.wekeep_sku_mappings for all to authenticated
  using (
    exists (
      select 1 from public.app_user_roles r
      where r.user_id = auth.uid() and r.role = 'admin' and r.is_active
    )
  )
  with check (
    exists (
      select 1 from public.app_user_roles r
      where r.user_id = auth.uid() and r.role = 'admin' and r.is_active
    )
  );

grant select, insert, update, delete on public.wekeep_sku_mappings to authenticated;

