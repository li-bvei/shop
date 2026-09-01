<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// The public loyalty-card pages (/pc/*). Deliberately outside AppShell:
// no sidebar, no auth store, no admin chrome — just a phone-width card on
// a plain ground. Japanese-first (decision 15).
const { locale } = useI18n()
locale.value = 'ja'
</script>

<template>
  <div class="guest-shell">
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
  justify-content: center;
  padding: 20px 14px 40px;
}

.guest-main {
  width: 100%;
  max-width: 460px;
}
</style>
