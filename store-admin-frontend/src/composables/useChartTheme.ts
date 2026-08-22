import { computed } from 'vue'
import { usePreferenceStore } from '@/stores/preference'

const palettes = {
  light: {
    accent: '#0071e3',
    accentSoft: 'rgba(0, 113, 227, 0.08)',
    success: '#1ea672',
    danger: '#e0393e',
    textPrimary: '#1d1d1f',
    textSecondary: '#6e6e73',
    textTertiary: '#98989d',
    border: 'rgba(0, 0, 0, 0.07)',
    axisLine: 'rgba(0, 0, 0, 0.07)',
  },
  dark: {
    accent: '#0a84ff',
    accentSoft: 'rgba(10, 132, 255, 0.16)',
    success: '#30d158',
    danger: '#ff453a',
    textPrimary: '#f5f5f7',
    textSecondary: '#98989d',
    textTertiary: '#6e6e73',
    border: 'rgba(255, 255, 255, 0.1)',
    axisLine: 'rgba(255, 255, 255, 0.1)',
  },
}

export function useChartTheme() {
  const preference = usePreferenceStore()
  return computed(() => palettes[preference.theme])
}
