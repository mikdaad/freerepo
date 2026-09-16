/**
 * Supabase schema types.
 *
 * In a real project this file is generated (`npx supabase gen types typescript --project-id …`).
 * It is checked in by hand here so the repository is self-contained and so the contract the client
 * depends on is explicit. The matching server-side DDL lives in `supabase/migrations/`.
 *
 * Shape notes:
 *  • `timestamptz` arrives as an ISO-8601 **string** over PostgREST, not a Date.
 *  • `bigint` (`sync_version`) is requested as a JSON number by PostgREST, but older PostgREST
 *    versions and `count` aggregates can return it as a string, so mappers coerce defensively.
 *  • `numeric`/`double precision` are declared `number` here; `numeric` in particular is sometimes
 *    serialised as a string, which is why the stop mapper goes through `toFiniteNumber()`.
 */

export interface GtfsRouteRecord {
  route_id: string;
  route_short_name: string | null;
  route_long_name: string | null;
  route_type: number | null;
  route_color: string | null;
  route_text_color: string | null;
  updated_at: string;
  deleted_at: string | null;
  sync_version: number;
}

export interface GtfsStopRecord {
  stop_id: string;
  stop_name: string | null;
  stop_code: string | null;
  stop_lat: number;
  stop_lon: number;
  location_type: number | null;
  parent_station: string | null;
  updated_at: string;
  deleted_at: string | null;
  sync_version: number;
}

export interface GtfsTripRecord {
  trip_id: string;
  route_id: string;
  service_id: string;
  trip_headsign: string | null;
  direction_id: number | null;
  updated_at: string;
  deleted_at: string | null;
  sync_version: number;
}

export interface GtfsStopTimeRecord {
  trip_id: string;
  stop_sequence: number;
  stop_id: string;
  arrival_time: string | null;
  departure_time: string | null;
  pickup_type: number | null;
  updated_at: string;
  deleted_at: string | null;
  sync_version: number;
}

export interface GtfsCalendarRecord {
  service_id: string;
  monday: number;
  tuesday: number;
  wednesday: number;
  thursday: number;
  friday: number;
  saturday: number;
  sunday: number;
  start_date: string;
  end_date: string;
  updated_at: string;
  deleted_at: string | null;
  sync_version: number;
}

export interface GtfsCalendarDateRecord {
  service_id: string;
  date: string;
  exception_type: number;
  updated_at: string;
  deleted_at: string | null;
  sync_version: number;
}

/** Server table names, keyed by the client-side entity name. */
export const SUPABASE_TABLE_BY_ENTITY = {
  routes: 'gtfs_routes',
  stops: 'gtfs_stops',
  trips: 'gtfs_trips',
  stop_times: 'gtfs_stop_times',
  calendar: 'gtfs_calendar',
  calendar_dates: 'gtfs_calendar_dates',
} as const;

export type SupabaseGtfsTable =
  (typeof SUPABASE_TABLE_BY_ENTITY)[keyof typeof SUPABASE_TABLE_BY_ENTITY];

export type GtfsRecordByTable = {
  gtfs_routes: GtfsRouteRecord;
  gtfs_stops: GtfsStopRecord;
  gtfs_trips: GtfsTripRecord;
  gtfs_stop_times: GtfsStopTimeRecord;
  gtfs_calendar: GtfsCalendarRecord;
  gtfs_calendar_dates: GtfsCalendarDateRecord;
};

/**
 * Minimal `Database` generic accepted by `createClient`.
 * Only the tables the app reads are declared — this build never writes to the backend.
 */
export interface Database {
  public: {
    Tables: {
      gtfs_routes: {
        Row: GtfsRouteRecord;
        Insert: Partial<GtfsRouteRecord>;
        Update: Partial<GtfsRouteRecord>;
      };
      gtfs_stops: {
        Row: GtfsStopRecord;
        Insert: Partial<GtfsStopRecord>;
        Update: Partial<GtfsStopRecord>;
      };
      gtfs_trips: {
        Row: GtfsTripRecord;
        Insert: Partial<GtfsTripRecord>;
        Update: Partial<GtfsTripRecord>;
      };
      gtfs_stop_times: {
        Row: GtfsStopTimeRecord;
        Insert: Partial<GtfsStopTimeRecord>;
        Update: Partial<GtfsStopTimeRecord>;
      };
      gtfs_calendar: {
        Row: GtfsCalendarRecord;
        Insert: Partial<GtfsCalendarRecord>;
        Update: Partial<GtfsCalendarRecord>;
      };
      gtfs_calendar_dates: {
        Row: GtfsCalendarDateRecord;
        Insert: Partial<GtfsCalendarDateRecord>;
        Update: Partial<GtfsCalendarDateRecord>;
      };
    };
    Views: Record<never, never>;
    Functions: Record<never, never>;
  };
}
