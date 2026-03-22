export interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  updated_at?: string;
  bank_accounts: BankAccount[];
}

export interface BankAccount {
  id: number;
  account_number: string;
  account_type: string;
  balance: string;
  currency: string;
  is_active: boolean;
  owner_id: number;
  created_at: string;
  updated_at?: string;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface RegisterData {
  username: string;
  email: string;
  password: string;
  first_name: string;
  last_name: string;
}