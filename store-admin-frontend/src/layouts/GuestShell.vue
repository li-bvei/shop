<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AppLocale } from '@/i18n'

// The public loyalty-card pages (/pc/*). Deliberately outside AppShell:
// no sidebar, no auth store, no admin chrome — just a phone-width card on
// a plain ground. Japanese-first (decision 15), with an opt-in switch to
// Chinese kept in localStorage.
const GUEST_LANG_KEY = 'pc_lang'
const { locale } = useI18n()

function readStored(): AppLocale {
  try {
    const v = localStorage.getItem(GUEST_LANG_KEY)
    if (v === 'ja' || v === 'zh') return v
  } catch {
    /* private mode / storage disabled */
  }
  return 'ja'
}

// Restore whatever the locale was (an admin previewing /pc/*, or the i18n
// default) when we leave, so the guest choice never leaks into the admin UI.
const previousLocale = locale.value as AppLocale
const lang = ref<AppLocale>(readStored())
locale.value = lang.value

function setLang(next: AppLocale) {
  lang.value = next
  locale.value = next
  try {
    localStorage.setItem(GUEST_LANG_KEY, next)
  } catch {
    /* ignore */
  }
}

onBeforeUnmount(() => {
  locale.value = previousLocale
})
</script>

<template>
  <div class="guest-shell">
    <div class="guest-topbar">
      <div class="lang-toggle" role="group" aria-label="Language">
        <button type="button" :class="{ active: lang === 'ja' }" @click="setLang('ja')">日本語</button>
        <button type="button" :class="{ active: lang === 'zh' }" @click="setLang('zh')">中文</button>
      </div>
    </div>
    <main class="guest-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.guest-shell {
  min-height: 100vh;
  min-height: 100dvh;
  background: var(--bg);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px 14px 40px;
}

.guest-topbar {
  width: 100%;
  max-width: 460px;
  display: flex;
  justify-content: flex-end;
}

.lang-toggle {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 999px;
  overflow: hidden;
  background: var(--surface);
}

.lang-toggle button {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 5px 12px;
  cursor: pointer;
  line-height: 1.4;
}

.lang-toggle button.active {
  background: var(--accent);
  color: #fff;
}

.guest-main {
  width: 100%;
  max-width: 460px;
}
</style>
