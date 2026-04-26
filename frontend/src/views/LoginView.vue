<template>
  <section class="card auth-card">
    <h2>Login</h2>
    <form @submit.prevent="submit">
      <label>
        Email
        <input v-model="form.email" type="email" required />
      </label>
      <label>
        Password
        <input v-model="form.password" type="password" required minlength="8" />
      </label>
      <button :disabled="loading" type="submit">{{ loading ? 'Please wait...' : 'Submit' }}</button>
    </form>
    <p class="error" v-if="error">{{ error }}</p>
    <p class="muted">Account is provisioned by server instance configuration.</p>
  </section>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, setTokens } from '../api'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const form = reactive({ email: '', password: '' })

async function submit() {
  loading.value = true
  error.value = ''
  try {
    const payload = { email: form.email, password: form.password }
    const tokens = await api.login(payload)
    setTokens(tokens)
    router.push('/')
  } catch (e) {
    error.value = e.message || 'Authentication failed'
  } finally {
    loading.value = false
  }
}
</script>
