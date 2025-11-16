import { AnimatePresence } from "framer-motion";
import { Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import LandingPage from "./pages/LandingPage";
import PricingPage from "./pages/PricingPage";
import IntakeFormPage from "./pages/IntakeFormPage";

function App() {
  const location = useLocation();

  return (
    <Layout>
      <AnimatePresence mode="wait" initial={false}>
        <Routes location={location} key={location.pathname}>
          <Route path="/" element={<LandingPage />} />
          <Route path="/pricing" element={<PricingPage />} />
          <Route path="/business-plan-form" element={<IntakeFormPage />} />
        </Routes>
      </AnimatePresence>
    </Layout>
  );
}

export default App;

