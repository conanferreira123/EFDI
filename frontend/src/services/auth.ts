import { apiRequest } from "./client";
import type { Token, UserResponse } from "@/types/api";
import type { UserRole } from "@/types/domain";

export interface RegisterPayload {
  username: string;
  email: string;
  full_name: string;
  password: string;
  role: UserRole;
}

export const authApi = {
  login: (username: string, password: string) =>
    apiRequest<Token>("/auth/login", { method: "POST", body: { username, password } }),

  register: (payload: RegisterPayload) =>
    apiRequest<UserResponse>("/auth/register", { method: "POST", body: payload }),

  me: () => apiRequest<UserResponse>("/auth/me"),
};
