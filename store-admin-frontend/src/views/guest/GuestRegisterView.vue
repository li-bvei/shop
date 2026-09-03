<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ApiError } from '@/api/http'
import { AlreadyRegisteredError, fetchStoreContext, register, type StoreContext } from '@/api/guest'

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
const brandName = computed(() =>
  store.value ? (locale.value === 'ja' ? store.value.orgNameJa : store.value.orgNameZh) : '',
)

onMounted(async () => {
  if (!storeToken.value) return
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
  <div class="card">
    <div v-if="brandLogo || brandName" class="brand">
      <img v-if="brandLogo" :src="brandLogo" alt="" class="brand-logo" />
      <span v-else class="brand-name">{{ brandName }}</span>
    </div>
    <h1>{{ t('guest.registerTitle') }}</h1>
    <p class="lead">{{ t('guest.registerLead') }}</p>

    <div v-if="!storeToken" class="notice notice-error">{{ t('guest.errStoreToken') }}</div>

    <form v-else class="form" @submit.prevent="submit">
      <label class="field">
        <span class="label">{{ t('guest.phone') }} <em>{{ t('guest.required') }}</em></span>
        <input
          v-model="form.phone"
          type="tel"
          inputmode="numeric"
          autocomplete="tel"
          :placeholder="t('guest.phonePlaceholder')"
        />
      </label>

      <label class="field">
        <span class="label">{{ t('guest.name') }} <em class="opt">{{ t('guest.optional') }}</em></span>
        <input v-model="form.name" type="text" autocomplete="name" :placeholder="t('guest.namePlaceholder')" />
      </label>

      <div class="field">
        <span class="label">{{ t('guest.birthday') }} <em>{{ t('guest.required') }}</em></span>
        <div class="birthday-row">
          <select v-model="form.birthdayMonth">
            <option value="">{{ t('guest.month') }}</option>
            <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
          </select>
          <select v-model="form.birthdayDay">
            <option value="">{{ t('guest.day') }}</option>
            <option v-for="d in days" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <span class="hint">{{ t('guest.birthdayHintRequired') }}</span>
      </div>

      <label class="field">
        <span class="label">{{ t('guest.pin') }} <em class="opt">{{ t('guest.optional') }}</em></span>
        <input
          v-model="form.pin"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          maxlength="6"
          :placeholder="t('guest.pinPlaceholder')"
          @input="form.pin = form.pin.replace(/\D/g, '').slice(0, 6)"
        />
        <span class="hint" :class="{ 'hint-error': pinError }">
          {{ pinError ? t('guest.errPinFormat') : t('guest.pinHint') }}
        </span>
      </label>

      <label class="consent">
        <input v-model="form.consent" type="checkbox" />
        <span>{{ t('guest.consent') }}</span>
      </label>

      <div v-if="errorMsg" class="notice notice-error">{{ errorMsg }}</div>

      <button type="submit" class="btn-primary" :disabled="!canSubmit">
        {{ submitting ? t('guest.submitting') : t('guest.registerSubmit') }}
      </button>
      <router-link :to="{ name: 'guest-login' }" class="link-alt">{{ t('guest.haveCard') }}</router-link>
    </form>
  </div>
</template>

<style scoped>
.card {
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 28px 24px 24px;
  margin-top: 24px;
}

.brand {
  display: flex;
  justify-content: center;
  margin-bottom: 14px;
}

.brand-logo {
  max-height: 44px;
  max-width: 65%;
  object-fit: contain;
}

.brand-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
}

h1 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 6px;
}

.lead {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 20px;
  line-height: 1.5;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.label {
  font-size: 12.5px;
  color: var(--text-secondary);
  font-weight: 600;
}

.label em {
  color: var(--danger);
  font-style: normal;
  font-size: 11px;
}

.label em.opt {
  color: var(--text-tertiary);
}

input[type='tel'],
input[type='text'],
select {
  width: 100%;
  height: 44px;
  padding: 0 12px;
  font-size: 15px;
  color: var(--text-primary);
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  outline: none;
  box-sizing: border-box;
}

input:focus,
select:focus {
  border-color: var(--accent);
}

.birthday-row {
  display: flex;
  gap: 10px;
}

.hint {
  font-size: 11.5px;
  color: var(--text-tertiary);
}

.hint-error {
  color: var(--danger);
}

.consent {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-secondary);
  line-height: 1.5;
  cursor: pointer;
}

.consent input {
  margin-top: 2px;
  flex-shrink: 0;
}

.btn-primary {
  height: 46px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.link-alt {
  text-align: center;
  font-size: 12.5px;
  color: var(--accent);
  text-decoration: none;
}

.notice {
  font-size: 12.5px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  line-height: 1.5;
}

.notice-error {
  background: var(--danger-light);
  color: var(--danger);
}
</style>
