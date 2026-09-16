-- =============================================================================================
-- Transit Pulse — GTFS sync schema (Supabase / PostgreSQL)
--
-- Apply with the Supabase CLI (`supabase db push`) or paste into the SQL editor.
--
-- Design contract with the client (src/sync/supabaseTransport.ts):
--   * ONE shared sequence, `gtfs_sync_version_seq`, feeds a `sync_version` column on every table.
--     A trigger bumps it on every INSERT/UPDATE. Because the sequence is shared, `sync_version` is
--     a *global total order across all six tables* — which is what lets the client keep a single
--     integer cursor per table and page with `WHERE sync_version > :cursor ORDER BY sync_version`.
--   * Deletes are SOFT (`deleted_at timestamptz`). A hard DELETE is invisible to the client and
--     would leave phantom rows on every device; a tombstone travels through the same ordered stream
--     instead. Keep this rule even for "obviously wrong" rows: soft-delete, then purge out of band.
--   * `updated_at` is human-facing metadata only. Never use it as the cursor: two rows written in
--     the same millisecond would be skipped or duplicated depending on the comparison operator.
--
-- ETL note: load GTFS with the anon/authenticated roles blocked (only service_role writes). The
-- client is SELECT-only by policy.
-- =============================================================================================

begin;

-- ---------------------------------------------------------------------------------------------
-- Sync ordering primitive
-- ---------------------------------------------------------------------------------------------
create sequence if not exists public.gtfs_sync_version_seq as bigint
  start with 1 increment by 1 no cycle cache 1;

create or replace function public.gtfs_mark_sync()
returns trigger
language plpgsql
as $$
begin
  -- Every mutation, including a soft delete, receives a strictly larger version.
  new.sync_version := nextval('public.gtfs_sync_version_seq');
  new.updated_at   := now();
  return new;
end;
$$;

comment on function public.gtfs_mark_sync() is
  'Stamps gtfs_* rows with a globally monotonic sync_version + updated_at on every insert/update.';

-- ---------------------------------------------------------------------------------------------
-- Feed tables
-- ---------------------------------------------------------------------------------------------

create table if not exists public.gtfs_routes (
  route_id         text primary key,
  route_short_name text,
  route_long_name  text,
  route_type       integer,
  route_color      text,
  route_text_color text,
  updated_at       timestamptz not null default now(),
  deleted_at       timestamptz,
  sync_version     bigint not null default 0
);

create table if not exists public.gtfs_stops (
  stop_id        text primary key,
  stop_name      text,
  stop_code      text,
  stop_lat       double precision not null,
  stop_lon       double precision not null,
  location_type  integer,
  parent_station text,
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  sync_version   bigint not null default 0,
  constraint gtfs_stops_lat_range check (stop_lat between -90 and 90),
  constraint gtfs_stops_lon_range check (stop_lon between -180 and 180)
);

create table if not exists public.gtfs_trips (
  trip_id       text primary key,
  route_id      text not null references public.gtfs_routes (route_id) on delete cascade,
  service_id    text not null,
  trip_headsign text,
  direction_id  integer,
  updated_at    timestamptz not null default now(),
  deleted_at    timestamptz,
  sync_version  bigint not null default 0
);

create table if not exists public.gtfs_stop_times (
  trip_id       text not null references public.gtfs_trips (trip_id) on delete cascade,
  stop_sequence integer not null,
  stop_id       text not null references public.gtfs_stops (stop_id) on delete cascade,
  arrival_time   text,
  departure_time text,
  pickup_type    integer,
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  sync_version   bigint not null default 0,
  primary key (trip_id, stop_sequence),
  -- GTFS allows hours >= 24; the format check only enforces the shape.
  constraint gtfs_stop_times_arrival_shape
    check (arrival_time   is null or arrival_time   ~ '^\d{1,3}:[0-5]\d(:[0-5]\d)?$'),
  constraint gtfs_stop_times_departure_shape
    check (departure_time is null or departure_time ~ '^\d{1,3}:[0-5]\d(:[0-5]\d)?$')
);

create table if not exists public.gtfs_calendar (
  service_id text primary key,
  monday     integer not null default 0,
  tuesday    integer not null default 0,
  wednesday  integer not null default 0,
  thursday   integer not null default 0,
  friday     integer not null default 0,
  saturday   integer not null default 0,
  sunday     integer not null default 0,
  start_date text not null,
  end_date   text not null,
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  sync_version bigint not null default 0,
  constraint gtfs_calendar_dates_shape check (start_date ~ '^\d{8}$' and end_date ~ '^\d{8}$')
);

create table if not exists public.gtfs_calendar_dates (
  service_id     text not null,
  date           text not null,
  exception_type integer not null check (exception_type in (1, 2)),
  updated_at     timestamptz not null default now(),
  deleted_at     timestamptz,
  sync_version   bigint not null default 0,
  primary key (service_id, date),
  constraint gtfs_calendar_dates_date_shape check (date ~ '^\d{8}$')
);

-- ---------------------------------------------------------------------------------------------
-- Triggers: attach the version stamp
-- ---------------------------------------------------------------------------------------------
do $$
declare
  target_table text;
begin
  foreach target_table in array array[
    'gtfs_routes', 'gtfs_stops', 'gtfs_trips', 'gtfs_stop_times',
    'gtfs_calendar', 'gtfs_calendar_dates'
  ]
  loop
    execute format('drop trigger if exists %I on public.%I', target_table || '_sync', target_table);
    execute format(
      'create trigger %I before insert or update on public.%I
         for each row execute function public.gtfs_mark_sync()',
      target_table || '_sync', target_table
    );
  end loop;
end;
$$;

-- ---------------------------------------------------------------------------------------------
-- Indexes: the client's only read pattern is `sync_version > $1 ORDER BY sync_version`
-- ---------------------------------------------------------------------------------------------
create index if not exists gtfs_routes_sync_idx         on public.gtfs_routes (sync_version);
create index if not exists gtfs_stops_sync_idx          on public.gtfs_stops (sync_version);
create index if not exists gtfs_trips_sync_idx          on public.gtfs_trips (sync_version);
create index if not exists gtfs_stop_times_sync_idx     on public.gtfs_stop_times (sync_version);
create index if not exists gtfs_calendar_sync_idx       on public.gtfs_calendar (sync_version);
create index if not exists gtfs_calendar_dates_sync_idx on public.gtfs_calendar_dates (sync_version);

-- Serving the feed by stop (useful for a future "departures only" delta endpoint).
create index if not exists gtfs_stop_times_stop_idx on public.gtfs_stop_times (stop_id);

-- ---------------------------------------------------------------------------------------------
-- Row Level Security: anonymous read-only access
-- ---------------------------------------------------------------------------------------------
alter table public.gtfs_routes         enable row level security;
alter table public.gtfs_stops          enable row level security;
alter table public.gtfs_trips          enable row level security;
alter table public.gtfs_stop_times     enable row level security;
alter table public.gtfs_calendar       enable row level security;
alter table public.gtfs_calendar_dates enable row level security;

do $$
declare
  target_table text;
begin
  foreach target_table in array array[
    'gtfs_routes', 'gtfs_stops', 'gtfs_trips', 'gtfs_stop_times',
    'gtfs_calendar', 'gtfs_calendar_dates'
  ]
  loop
    execute format('drop policy if exists %I on public.%I', target_table || '_read', target_table);
    execute format(
      'create policy %I on public.%I for select to anon, authenticated using (true)',
      target_table || '_read', target_table
    );
    -- No INSERT/UPDATE/DELETE policies exist: writes require the service_role key, which must
    -- never ship inside the app bundle.
  end loop;
end;
$$;

grant usage on schema public to anon, authenticated;
grant select on
  public.gtfs_routes, public.gtfs_stops, public.gtfs_trips,
  public.gtfs_stop_times, public.gtfs_calendar, public.gtfs_calendar_dates
to anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Operational helper: how far behind is a device's cursor allowed to be?
-- ---------------------------------------------------------------------------------------------
create or replace view public.gtfs_sync_health as
select 'gtfs_routes' as table_name,
       count(*) as rows,
       count(*) filter (where deleted_at is not null) as tombstoned,
       max(sync_version) as head_version
  from public.gtfs_routes
union all
select 'gtfs_stops', count(*), count(*) filter (where deleted_at is not null), max(sync_version)
  from public.gtfs_stops
union all
select 'gtfs_trips', count(*), count(*) filter (where deleted_at is not null), max(sync_version)
  from public.gtfs_trips
union all
select 'gtfs_stop_times', count(*), count(*) filter (where deleted_at is not null), max(sync_version)
  from public.gtfs_stop_times
union all
select 'gtfs_calendar', count(*), count(*) filter (where deleted_at is not null), max(sync_version)
  from public.gtfs_calendar
union all
select 'gtfs_calendar_dates', count(*), count(*) filter (where deleted_at is not null), max(sync_version)
  from public.gtfs_calendar_dates;

comment on view public.gtfs_sync_health is
  'Per-table row counts and the current cursor head. `select * from gtfs_sync_health;` answers
   "did my ETL actually publish anything?"';

commit;

-- =============================================================================================
-- Loading GTFS (run with the service_role key, never from the app):
--
--   1. Upsert routes, stops, calendar, calendar_dates first, then trips, then stop_times.
--   2. Because `ON CONFLICT DO UPDATE` fires the row trigger, changed rows get a new sync_version
--      and every device picks them up on its next pass.
--   3. To remove a feed row:  update gtfs_stops set deleted_at = now() where stop_id = '...';
--      Then, only after every device has caught up (compare against gtfs_sync_health), run the
--      physical cleanup:  delete from gtfs_stop_times where deleted_at < now() - interval '90 days';
-- =============================================================================================
