"use server";

import { signIn, signOut } from "@/lib/auth";

export async function signInWithDiscord() {
  await signIn("discord", { redirectTo: "/dashboard" });
}

export async function signOutUser() {
  await signOut({ redirectTo: "/" });
}
