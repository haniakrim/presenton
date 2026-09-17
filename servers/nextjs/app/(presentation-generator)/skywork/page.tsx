import React from "react";
import { Metadata } from "next";
import SkyworkResultPage from "./components/SkyworkResultPage";

export const metadata: Metadata = {
  title: "Generating with Skywork",
  description: "Your Smart presentation is being generated via Skywork.",
};

const page = () => {
  return (
    <div className="relative min-h-screen" translate="no">
      <SkyworkResultPage />
    </div>
  );
};

export default page;
