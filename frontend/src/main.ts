import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { installElementPlus } from './plugins/elementPlus'
import './styles/tokens.css'
import './styles/element-theme.css'
import './styles/base.css'
import './styles/utilities.css'
import './styles/main.css'

const app = createApp(App).use(createPinia()).use(router)
installElementPlus(app)
app.mount('#app')
