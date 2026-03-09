export type Json = string | number | boolean | null | { [key: string]: Json | undefined } | Json[];

export interface Database {
  public: {
    Tables: {
      users: {
        Row: {
          id: string;
          email: string;
          tier: "free" | "starter" | "pro";
          stripe_customer_id: string | null;
          stripe_subscription_id: string | null;
          subscription_status: string;
          subscription_current_period_end: string | null;
          telegram_chat_id: string | null;
          gmail_connected: boolean;
          onboarding_completed: boolean;
          daily_apply_limit: number;
          is_admin: boolean;
          approval_status: "pending" | "approved" | "rejected";
          full_name: string | null;
          avatar_url: string | null;
          requested_at: string;
          approved_at: string | null;
          approved_by: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["users"]["Row"], "created_at" | "updated_at"> & {
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["users"]["Insert"]>;
      };
      user_profiles: {
        Row: {
          id: string;
          user_id: string;
          first_name: string | null;
          last_name: string | null;
          phone: string | null;
          linkedin_url: string | null;
          github_url: string | null;
          portfolio_url: string | null;
          current_company: string | null;
          current_title: string | null;
          years_experience: number | null;
          education_level: string | null;
          school_name: string | null;
          degree: string | null;
          graduation_year: number | null;
          work_authorization: string | null;
          requires_sponsorship: boolean;
          gender: string | null;
          race_ethnicity: string | null;
          veteran_status: string | null;
          disability_status: string | null;
          cover_letter_template: string | null;
          answer_key_json: Json;
          created_at: string;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["user_profiles"]["Row"], "id" | "created_at" | "updated_at"> & {
          id?: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["user_profiles"]["Insert"]>;
      };
      user_resumes: {
        Row: {
          id: string;
          user_id: string;
          storage_path: string;
          file_name: string;
          is_default: boolean;
          target_keywords: string[];
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["user_resumes"]["Row"], "id" | "created_at"> & {
          id?: string;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["user_resumes"]["Insert"]>;
      };
      user_job_preferences: {
        Row: {
          id: string;
          user_id: string;
          target_titles: string[];
          target_keywords: string[];
          excluded_titles: string[];
          excluded_companies: string[];
          min_salary: number | null;
          preferred_locations: string[];
          remote_only: boolean;
          auto_apply: boolean;
          max_daily: number;
          created_at: string;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["user_job_preferences"]["Row"], "id" | "created_at" | "updated_at"> & {
          id?: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["user_job_preferences"]["Insert"]>;
      };
      discovered_jobs: {
        Row: {
          id: string;
          external_id: string;
          ats: "greenhouse" | "lever" | "ashby" | "workday";
          title: string;
          company: string;
          location: string | null;
          department: string | null;
          apply_url: string;
          description_snippet: string | null;
          posted_at: string | null;
          discovered_at: string;
          board_token: string | null;
          is_active: boolean;
        };
        Insert: Omit<Database["public"]["Tables"]["discovered_jobs"]["Row"], "id" | "discovered_at"> & {
          id?: string;
          discovered_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["discovered_jobs"]["Insert"]>;
      };
      user_job_matches: {
        Row: {
          id: string;
          user_id: string;
          job_id: string;
          match_score: number | null;
          status: "pending" | "approved" | "skipped" | "queued" | "applied";
          created_at: string;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["user_job_matches"]["Row"], "id" | "created_at" | "updated_at"> & {
          id?: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["user_job_matches"]["Insert"]>;
      };
      application_queue: {
        Row: {
          id: string;
          user_id: string;
          job_id: string;
          status: "pending" | "locked" | "processing" | "submitted" | "failed" | "cancelled";
          locked_by: string | null;
          locked_at: string | null;
          attempts: number;
          max_attempts: number;
          error: string | null;
          priority: number;
          created_at: string;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["application_queue"]["Row"], "id" | "created_at" | "updated_at"> & {
          id?: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["application_queue"]["Insert"]>;
      };
      applications: {
        Row: {
          id: string;
          user_id: string;
          job_id: string;
          queue_id: string | null;
          company: string;
          title: string;
          ats: string;
          apply_url: string | null;
          status: "submitted" | "failed" | "verified";
          screenshot_url: string | null;
          error: string | null;
          applied_at: string;
          metadata: Json;
        };
        Insert: Omit<Database["public"]["Tables"]["applications"]["Row"], "id" | "applied_at"> & {
          id?: string;
          applied_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["applications"]["Insert"]>;
      };
      gmail_tokens: {
        Row: {
          id: string;
          user_id: string;
          access_token_encrypted: string;
          refresh_token_encrypted: string;
          token_expiry: string | null;
          email: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["gmail_tokens"]["Row"], "id" | "created_at" | "updated_at"> & {
          id?: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["gmail_tokens"]["Insert"]>;
      };
      invite_codes: {
        Row: {
          id: string;
          code: string;
          max_uses: number;
          used_count: number;
          created_by: string | null;
          expires_at: string | null;
          is_active: boolean;
          created_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["invite_codes"]["Row"], "id" | "created_at"> & {
          id?: string;
          created_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["invite_codes"]["Insert"]>;
      };
      knowledge_base: {
        Row: {
          id: string;
          key: string;
          value: Json;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["knowledge_base"]["Row"], "id" | "updated_at"> & {
          id?: string;
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["knowledge_base"]["Insert"]>;
      };
      system_config: {
        Row: {
          key: string;
          value: Json;
          updated_at: string;
        };
        Insert: Omit<Database["public"]["Tables"]["system_config"]["Row"], "updated_at"> & {
          updated_at?: string;
        };
        Update: Partial<Database["public"]["Tables"]["system_config"]["Insert"]>;
      };
    };
    Functions: {
      claim_next_job: {
        Args: { p_worker_id: string };
        Returns: Database["public"]["Tables"]["application_queue"]["Row"][];
      };
      recover_stale_locks: {
        Args: Record<string, never>;
        Returns: number;
      };
      approve_user: {
        Args: { p_user_id: string; p_admin_id: string };
        Returns: void;
      };
      reject_user: {
        Args: { p_user_id: string; p_admin_id: string };
        Returns: void;
      };
    };
  };
}
