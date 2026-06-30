import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import App from "./App"
import { BookcheckProvider } from "@/lib/store"
import { ThemeProvider } from "@/lib/theme"
import { ToastProvider } from "@/lib/toast"
import "./index.css"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <BookcheckProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </BookcheckProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
)
