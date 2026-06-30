import { Routes, Route } from "react-router-dom"
import Layout from "@/components/Layout"
import Home from "@/pages/Home"
import Chat from "@/pages/Chat"
import Characters from "@/pages/Characters"
import Relations from "@/pages/Relations"
import Locations from "@/pages/Locations"
import Story from "@/pages/Story"
import Timeline from "@/pages/Timeline"
import Report from "@/pages/Report"

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/characters" element={<Characters />} />
        <Route path="/relations" element={<Relations />} />
        <Route path="/locations" element={<Locations />} />
        <Route path="/story" element={<Story />} />
        <Route path="/timeline" element={<Timeline />} />
        <Route path="/report" element={<Report />} />
      </Route>
    </Routes>
  )
}
