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
    <div class="guest-canvas guest-topbar">
      <div class="lang-toggle" role="group" aria-label="Language">
        <button type="button" :class="{ active: lang === 'ja' }" @click="setLang('ja')">JA</button>
        <span aria-hidden="true">/</span>
        <button type="button" :class="{ active: lang === 'zh' }" @click="setLang('zh')">中文</button>
      </div>
    </div>
    <main class="guest-canvas guest-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.guest-shell {
  position: relative;
  min-height: 100vh;
  min-height: 100dvh;
  background: #fff;
  padding: 14px 22px 48px;
}

.guest-topbar {
  position: absolute;
  top: 16px;
  left: 0;
  right: 0;
  z-index: 5;
  display: flex;
  justify-content: flex-end;
  padding: 0 22px;
  pointer-events: none;
}

.lang-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border: 1px solid var(--guest-rule);
  border-radius: 999px;
  background: #fff;
  color: #c3c7ca;
  font-size: 10px;
  pointer-events: auto;
}

.lang-toggle button {
  border: none;
  background: transparent;
  color: #a5aaae;
  font-family: inherit;
  font-size: 11px;
  padding: 2px 3px;
  line-height: 1.3;
  cursor: pointer;
}

.lang-toggle button.active {
  color: var(--guest-green-dark);
  font-weight: 800;
}

.guest-main {
  padding-top: 4px;
}

@media (max-width: 360px) {
  .guest-shell {
    padding-inline: 18px;
  }
  .guest-topbar {
    padding-inline: 18px;
  }
}
</style>
