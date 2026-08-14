create table if not exists public.calendar_events (
    id text primary key,
    event_date date not null,
    title text not null,
    info text not null default '',
    attachments jsonb not null default '[]'::jsonb,
    created_by uuid default auth.uid(),
    updated_at timestamptz not null default now()
);

alter table public.calendar_events
add column if not exists attachments jsonb not null default '[]'::jsonb;

alter table public.calendar_events enable row level security;

drop policy if exists "calendar_events_authenticated_select" on public.calendar_events;
create policy "calendar_events_authenticated_select"
on public.calendar_events for select
to authenticated
using (true);

insert into storage.buckets (id, name, public, file_size_limit)
values ('calendar-attachments', 'calendar-attachments', false, 20971520)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit;

drop policy if exists "calendar_attachments_authenticated_select" on storage.objects;
create policy "calendar_attachments_authenticated_select"
on storage.objects for select
to authenticated
using (bucket_id = 'calendar-attachments');

drop policy if exists "calendar_attachments_authenticated_insert" on storage.objects;
create policy "calendar_attachments_authenticated_insert"
on storage.objects for insert
to authenticated
with check (bucket_id = 'calendar-attachments');

drop policy if exists "calendar_attachments_authenticated_update" on storage.objects;
create policy "calendar_attachments_authenticated_update"
on storage.objects for update
to authenticated
using (bucket_id = 'calendar-attachments')
with check (bucket_id = 'calendar-attachments');

drop policy if exists "calendar_attachments_authenticated_delete" on storage.objects;
create policy "calendar_attachments_authenticated_delete"
on storage.objects for delete
to authenticated
using (bucket_id = 'calendar-attachments');

drop policy if exists "calendar_events_authenticated_insert" on public.calendar_events;
create policy "calendar_events_authenticated_insert"
on public.calendar_events for insert
to authenticated
with check (true);

drop policy if exists "calendar_events_authenticated_update" on public.calendar_events;
create policy "calendar_events_authenticated_update"
on public.calendar_events for update
to authenticated
using (true)
with check (true);

drop policy if exists "calendar_events_authenticated_delete" on public.calendar_events;
create policy "calendar_events_authenticated_delete"
on public.calendar_events for delete
to authenticated
using (true);
