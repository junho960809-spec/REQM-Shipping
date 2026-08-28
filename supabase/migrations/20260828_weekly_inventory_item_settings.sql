create table if not exists public.weekly_inventory_item_settings (
  item_code text primary key,
  item_name text not null default '',
  base_unit_cost numeric(18,6) not null default 0 check (base_unit_cost >= 0),
  is_active boolean not null default true,
  display_order integer not null default 999999,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id)
);

create index if not exists weekly_inventory_item_settings_active_idx
  on public.weekly_inventory_item_settings (is_active, display_order, item_code);

alter table public.weekly_inventory_item_settings enable row level security;

drop policy if exists "authenticated users read weekly inventory prices"
  on public.weekly_inventory_item_settings;
create policy "authenticated users read weekly inventory prices"
  on public.weekly_inventory_item_settings for select to authenticated using (true);

drop policy if exists "admins write weekly inventory prices"
  on public.weekly_inventory_item_settings;
create policy "admins write weekly inventory prices"
  on public.weekly_inventory_item_settings for all to authenticated
  using (
    exists (
      select 1 from public.app_user_roles r
      where r.user_id = auth.uid() and r.role = 'admin'
    )
  )
  with check (
    exists (
      select 1 from public.app_user_roles r
      where r.user_id = auth.uid() and r.role = 'admin'
    )
  );

grant select, insert, update, delete on public.weekly_inventory_item_settings to authenticated;
