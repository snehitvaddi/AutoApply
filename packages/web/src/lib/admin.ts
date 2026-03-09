import { createClient } from "@supabase/supabase-js";

export async function isAdmin(userId: string): Promise<boolean> {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );
  const { data } = await supabase
    .from("users")
    .select("is_admin")
    .eq("id", userId)
    .single();
  return data?.is_admin === true;
}
