-- Supabase mode of the scouting page: run once in the project's SQL editor.
-- Every signed-in user reads and writes everything, so sign-ups must be off
-- (Authentication > Sign In / Providers > "Allow new users to sign up") and the
-- users added by hand (Authentication > Users > Add user, with "Auto Confirm User").

-- one row per player, team and config (tags, todos, template); body is the record the page saves
create table public.scouting_docs (
    kind text not null check (kind in ('player', 'team', 'config')),
    id text not null,
    body jsonb not null,
    client text,  -- the browser tab that wrote the row, so it skips its own live update
    primary key (kind, id)
);

alter table public.scouting_docs enable row level security;
revoke all on public.scouting_docs from anon;
grant select, insert, update, delete on public.scouting_docs to authenticated;
create policy "signed-in users read and write the notes" on public.scouting_docs
    for all to authenticated using (true) with check (true);

-- live updates between the users' browsers
alter publication supabase_realtime add table public.scouting_docs;

-- uploaded template and team logos: readable by link (the page loads them like its own files),
-- written by signed-in users only
insert into storage.buckets (id, name, public) values ('scouting', 'scouting', true);
create policy "signed-in users manage the scouting files" on storage.objects
    for all to authenticated using (bucket_id = 'scouting') with check (bucket_id = 'scouting');
