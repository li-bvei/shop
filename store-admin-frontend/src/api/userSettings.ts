import { http } from './http'
import type { AppLocale } from '@/i18n'

export type AppTheme = 'light' | 'dark'

export interface UserPreference {
  locale: AppLocale
  theme: AppTheme
}

interface UserPreferenceDto {
  locale: AppLocale
  theme: AppTheme
  updated_at: string
}

export async function fetchUserPreference(): Promise<UserPreference> {
  const dto = await http.get<UserPreferenceDto>('/auth/preference/')
  return { locale: dto.locale, theme: dto.theme }
}

export async function saveUserPreference(preference: UserPreference): Promise<void> {
  await http.patch('/auth/preference/', preference)
}
