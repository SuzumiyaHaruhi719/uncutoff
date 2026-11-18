import { cookies } from "next/headers";

export function readTheme() {
  return cookies().get("theme")?.value;
}
