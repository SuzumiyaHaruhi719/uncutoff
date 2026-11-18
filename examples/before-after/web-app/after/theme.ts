import { cookies } from "next/headers";

export async function readTheme() {
  const cookieStore = await cookies();
  return cookieStore.get("theme")?.value;
}
