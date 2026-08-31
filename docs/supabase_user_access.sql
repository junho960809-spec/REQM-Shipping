-- REQM 사용자 권한·작업 이력 마이그레이션
-- Supabase Dashboard > SQL Editor에서 한 번 실행하세요.

create table if not exists public.app_user_profiles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    email text not null,
    last_login_at timestamptz not null default now(),
    created_at timestamptz not null default now()
);

create table if not exists public.app_user_roles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    role text not null default 'viewer' check (role in ('admin', 'viewer')),
    can_ecount_transfer boolean not null default false,
    is_active boolean not null default true,
    updated_at timestamptz not null default now()
);

alter table public.app_user_roles add column if not exists can_ecount_transfer boolean not null default false;
alter table public.app_user_roles add column if not exists is_active boolean not null default true;
alter table public.app_user_roles add column if not exists updated_at timestamptz not null default now();
create unique index if not exists app_user_roles_user_id_key on public.app_user_roles(user_id);

create table if not exists public.app_work_audit (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    user_id uuid not null references auth.users(id),
    user_email text not null,
    event_type text not null,
    entity_type text not null,
    entity_key text not null default '',
    details jsonb not null default '{}'::jsonb
);
create index if not exists app_work_audit_created_at_idx on public.app_work_audit(created_at desc);

alter table public.app_user_profiles enable row level security;
alter table public.app_user_roles enable row level security;
alter table public.app_work_audit enable row level security;

create or replace function public.reqm_is_admin()
returns boolean language sql stable security definer set search_path = public as $$
    select auth.uid() = 'c7937d51-1a14-47aa-987e-6254c6c79014'::uuid
        or exists (
            select 1 from public.app_user_roles
            where user_id = auth.uid() and role = 'admin' and is_active
        );
$$;

create or replace function public.ensure_current_reqm_profile()
returns void language plpgsql security definer set search_path = public as $$
begin
    insert into public.app_user_profiles (user_id, email, last_login_at)
    values (auth.uid(), coalesce(auth.jwt() ->> 'email', ''), now())
    on conflict (user_id) do update
      set email = excluded.email, last_login_at = excluded.last_login_at;
end;
$$;

-- 관리자 화면의 이메일 등록/권한 저장용. 이메일은 Supabase Authentication에 먼저 만들어져 있어야 합니다.
create or replace function public.admin_set_reqm_user_access(
    p_email text,
    p_role text default 'viewer',
    p_can_ecount_transfer boolean default false,
    p_is_active boolean default true
)
returns table(user_id uuid, email text, role text, can_ecount_transfer boolean, is_active boolean, updated_at timestamptz)
language plpgsql security definer set search_path = public, auth as $$
declare target_user auth.users%rowtype;
begin
    if not public.reqm_is_admin() then raise exception '관리자만 사용자 권한을 변경할 수 있습니다.' using errcode = '42501'; end if;
    select * into target_user from auth.users where lower(email) = lower(trim(p_email));
    if not found then raise exception '이메일 계정을 찾지 못했습니다. 먼저 Supabase Authentication에서 해당 사용자를 생성하세요.'; end if;
    if p_role not in ('admin', 'viewer') then raise exception '지원하지 않는 역할입니다.'; end if;
    insert into public.app_user_profiles (user_id, email, last_login_at)
      values (target_user.id, target_user.email, now())
      on conflict (user_id) do update set email = excluded.email;
    insert into public.app_user_roles (user_id, role, can_ecount_transfer, is_active, updated_at)
      values (target_user.id, p_role, p_can_ecount_transfer, p_is_active, now())
      on conflict (user_id) do update set role = excluded.role, can_ecount_transfer = excluded.can_ecount_transfer,
        is_active = excluded.is_active, updated_at = excluded.updated_at;
    return query select target_user.id, target_user.email, p_role, p_can_ecount_transfer, p_is_active, now();
end;
$$;

create or replace function public.admin_list_reqm_user_access()
returns table(user_id uuid, email text, role text, can_ecount_transfer boolean, is_active boolean, updated_at timestamptz)
language sql stable security definer set search_path = public as $$
    select r.user_id, p.email, r.role, r.can_ecount_transfer, r.is_active, r.updated_at
    from public.app_user_roles r
    left join public.app_user_profiles p on p.user_id = r.user_id
    where public.reqm_is_admin()
    order by lower(coalesce(p.email, '')), r.updated_at desc;
$$;

create or replace function public.admin_list_reqm_work_audit(p_limit integer default 200)
returns table(created_at timestamptz, user_email text, event_type text, entity_type text, entity_key text, details jsonb)
language sql stable security definer set search_path = public as $$
    select a.created_at, a.user_email, a.event_type, a.entity_type, a.entity_key, a.details
    from public.app_work_audit a
    where public.reqm_is_admin()
    order by a.created_at desc
    limit greatest(1, least(coalesce(p_limit, 200), 500));
$$;

drop policy if exists app_user_profiles_own_select on public.app_user_profiles;
create policy app_user_profiles_own_select on public.app_user_profiles for select to authenticated using (user_id = auth.uid());
drop policy if exists app_user_roles_own_select on public.app_user_roles;
create policy app_user_roles_own_select on public.app_user_roles for select to authenticated using (user_id = auth.uid());
drop policy if exists app_work_audit_own_insert on public.app_work_audit;
create policy app_work_audit_own_insert on public.app_work_audit for insert to authenticated with check (user_id = auth.uid());

grant execute on function public.ensure_current_reqm_profile() to authenticated;
grant execute on function public.admin_set_reqm_user_access(text, text, boolean, boolean) to authenticated;
grant execute on function public.admin_list_reqm_user_access() to authenticated;
grant execute on function public.admin_list_reqm_work_audit(integer) to authenticated;
