<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError } from '@/api/http'
import {
  AlreadyRegisteredError,
  fetchStoreContext,
  getGuestToken,
  guestCheckin,
  register,
  type StoreContext,
} from '@/api/guest'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()

const storeToken = computed(() => (route.query.t as string) || '')
const submitting = ref(false)
const errorMsg = ref('')

// The chain's brand, resolved from the store-QR token — shown before the
// customer fills anything in so they know whose card they're opening.
const store = ref<StoreContext | null>(null)
const brandLogo = computed(() => store.value?.orgLogoUrl ?? '')
// Chain + branch, e.g. "○○グループ 心斎橋店" — shown next to the logo (not
// instead of it): a logo may be just a mark, so the name always appears.
const brandName = computed(() => {
  if (!store.value) return ''
  const chain = locale.value === 'ja' ? store.value.orgNameJa : store.value.orgNameZh
  const branch = locale.value === 'ja' ? store.value.branchNameJa : store.value.branchNameZh
  return [chain, branch].filter(Boolean).join(' ')
})

onMounted(async () => {
  if (!storeToken.value) return

  // Returning customer scanned the table QR — that's a self-service
  // check-in, not a re-registration. Record it and open their card.
  if (getGuestToken() && route.query.new === undefined) {
    try {
      const r = await guestCheckin(storeToken.value)
      router.replace({
        name: 'guest-card',
        query: { visited: r.alreadyCheckedIn ? 'again' : '1' },
      })
      return
    } catch {
      router.replace({ name: 'guest-card' })
      return
    }
  }

  try {
    store.value = await fetchStoreContext(storeToken.value)
  } catch {
    /* a bad/closed token surfaces on submit — no need to pre-empt it here */
  }
})

const form = reactive({
  phone: '',
  name: '',
  birthdayMonth: '',
  birthdayDay: '',
  pin: '',
  consent: false,
})

const pinError = computed(() => form.pin.length > 0 && !/^\d{6}$/.test(form.pin))

const months = Array.from({ length: 12 }, (_, i) => i + 1)
const days = Array.from({ length: 31 }, (_, i) => i + 1)

const canSubmit = computed(
  () =>
    storeToken.value &&
    form.phone.trim().length >= 10 &&
    !!birthdayMd.value &&
    form.consent &&
    !pinError.value &&
    !submitting.value,
)

const birthdayMd = computed(() => {
  if (!form.birthdayMonth || !form.birthdayDay) return ''
  return `${String(form.birthdayMonth).padStart(2, '0')}-${String(form.birthdayDay).padStart(2, '0')}`
})

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  errorMsg.value = ''
  try {
    await register({
      storeToken: storeToken.value,
      phone: form.phone.trim(),
      name: form.name.trim(),
      birthdayMd: birthdayMd.value,
      pin: form.pin,
      consent: form.consent,
    })
    router.replace({ name: 'guest-card', query: { welcome: '1' } })
  } catch (err) {
    if (err instanceof AlreadyRegisteredError) {
      // This number already has a card — send them to the recovery login.
      router.replace({ name: 'guest-login', query: { existing: '1' } })
      return
    }
    if (err instanceof ApiError) {
      const body = JSON.stringify(err.body)
      if (body.includes('store-token-invalid')) errorMsg.value = t('guest.errStoreToken')
      else if (body.includes('phone-invalid')) errorMsg.value = t('guest.errPhone')
      else if (body.includes('pin-too-common')) errorMsg.value = t('guest.errPinCommon')
      else if (body.includes('pin-must-be-6-digits')) errorMsg.value = t('guest.errPinFormat')
      else if (body.includes('consent')) errorMsg.value = t('guest.errConsent')
      else errorMsg.value = t('guest.errGeneric')
    } else {
      errorMsg.value = t('guest.errGeneric')
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="register-view">
    <div v-if="brandLogo || brandName" class="g-brand">
      <img v-if="brandLogo" :src="brandLogo" alt="" class="g-brand-logo" />
      <span v-if="brandName" class="g-brand-name">{{ brandName }}</span>
    </div>

    <section class="g-intro">
      <p class="g-eyebrow">{{ t('guest.eyebrowRegister') }}</p>
      <h1 class="g-title">{{ t('guest.registerTitle') }}</h1>
      <p class="g-lead">{{ t('guest.registerLead') }}</p>
    </section>

    <div v-if="!storeToken" class="g-notice is-error">{{ t('guest.errStoreToken') }}</div>

    <form v-else class="g-form" @submit.prevent="submit">
      <label class="g-field">
        <span class="g-field-label">{{ t('guest.phone') }} <em class="g-req">{{ t('guest.required') }}</em></span>
        <input
          v-model="form.phone"
          class="g-input"
          type="tel"
          inputmode="numeric"
          autocomplete="tel"
          :placeholder="t('guest.phonePlaceholder')"
        />
      </label>

      <label class="g-field">
        <span class="g-field-label">{{ t('guest.name') }} <em class="g-opt">{{ t('guest.optional') }}</em></span>
        <input v-model="form.name" class="g-input" type="text" autocomplete="name" :placeholder="t('guest.namePlaceholder')" />
      </label>

      <div class="g-field">
        <span class="g-field-label">{{ t('guest.birthday') }} <em class="g-req">{{ t('guest.required') }}</em></span>
        <div class="g-date-row">
          <select v-model="form.birthdayMonth" class="g-select">
            <option value="">{{ t('guest.month') }}</option>
            <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
          </select>
          <span>{{ t('guest.month') }}</span>
          <select v-model="form.birthdayDay" class="g-select">
            <option value="">{{ t('guest.day') }}</option>
            <option v-for="d in days" :key="d" :value="d">{{ d }}</option>
          </select>
          <span>{{ t('guest.day') }}</span>
        </div>
        <span class="g-hint">{{ t('guest.birthdayHintRequired') }}</span>
      </div>

      <label class="g-field">
        <span class="g-field-label">{{ t('guest.pin') }} <em class="g-opt">{{ t('guest.optional') }}</em></span>
        <input
          v-model="form.pin"
          class="g-input"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          maxlength="6"
          :placeholder="t('guest.pinPlaceholder')"
          @input="form.pin = form.pin.replace(/\D/g, '').slice(0, 6)"
        />
        <span class="g-hint" :class="{ 'is-error': pinError }">
          {{ pinError ? t('guest.errPinFormat') : t('guest.pinHint') }}
        </span>
      </label>

      <label class="g-consent">
        <input v-model="form.consent" type="checkbox" />
        <span>{{ t('guest.consent') }}</span>
      </label>

      <div v-if="errorMsg" class="g-notice is-error">{{ errorMsg }}</div>

      <button type="submit" class="g-btn-primary" :disabled="!canSubmit">
        {{ submitting ? t('guest.submitting') : t('guest.registerSubmit') }}
      </button>
      <router-link :to="{ name: 'guest-login' }" class="g-link">{{ t('guest.haveCard') }}</router-link>
    </form>
  </div>
</template>

<style scoped>
.register-view {
  padding-top: 4px;
}

/* Keep the parenthetical "(任意)" style label from the copy readable next to
   the tag chips. */
.g-field-label {
  flex-wrap: wrap;
}
</style>
