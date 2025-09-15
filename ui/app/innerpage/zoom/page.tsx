"use client";

import { useState, useEffect } from "react";
import { Divider } from "@nextui-org/divider";
import { Progress } from "@nextui-org/progress";
import { Chip } from "@nextui-org/chip";

const Button = ({ children, className = "", ...props }) => (
  <button
    className={`px-4 py-2 rounded-md font-medium bg-pink-600 text-white hover:bg-pink-700 transition ${className}`}
    {...props}
  >
    {children}
  </button>
);
export default function ZoomedVideoGenerator() {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [zoomedVideoUrl, setZoomedVideoUrl] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setVideoFile(file);
      setZoomedVideoUrl(null); // Reset zoomed video URL on new upload
      setError(null);
    }
  };

  useEffect(() => {
    // Cleanup the object URL when the component unmounts or file changes
    return () => {
      if (zoomedVideoUrl) {
        URL.revokeObjectURL(zoomedVideoUrl);
      }
    };
  }, [zoomedVideoUrl]);

  async function generateZoomedVideo() {
    if (!videoFile) return;
    
    setIsGenerating(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", videoFile);

      const response = await fetch("http://localhost:8080/process-video", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error("Failed to process video.");
      }

      // Receive the video file as a Blob from the backend
      const data = await response.blob();

      // Log the response data (for debugging)
      console.log("Video Blob received: ", data);

      // Create a Blob URL
      const videoUrl = URL.createObjectURL(data);

      // Save the binary file to disk (optional, for debugging)
      const fileName = "processed_video.mp4"; // You can change the name and format if needed
      const blob = new Blob([data], { type: "video/mp4" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = fileName;
      link.click(); // Trigger download

      // Set the zoomed video URL to the Blob URL
      setZoomedVideoUrl(videoUrl);
    } catch (e) {
      setError(e instanceof Error ? e.message : "An unknown error occurred");
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <div className="font-inter bg-white min-h-screen p-6 text-gray-800">
      <div className="max-w-2xl mx-auto flex flex-col gap-6">
        <h1 className="text-2xl font-bold text-pink-600">Zoomed Video Generator</h1>

        {/* Upload Video */}
        <input
          type="file"
          accept="video/*"
          onChange={handleFileChange}
          className="border border-pink-300 rounded-md px-4 py-2 w-full text-black"
        />

        {/* Video Preview */}
        {videoFile && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-gray-600">Preview</p>
            <video
              src={URL.createObjectURL(videoFile)}
              controls
              className="w-full max-w-lg border border-gray-300 bg-black rounded-md"
            />
          </div>
        )}

        {/* Generate Zoomed Video Button */}
        <Button onClick={generateZoomedVideo} disabled={!videoFile || isGenerating}>
          {isGenerating ? "Generating..." : "Generate Zoomed Video"}
        </Button>

        {isGenerating && (
          <Progress isIndeterminate aria-label="Generating zoomed video..." className="max-w-md" />
        )}

        {error && <p className="text-red-500">{error}</p>}

        {/* Display Zoomed Video
        {zoomedVideoUrl && (
          <div className="mt-4 p-4 border border-pink-300 rounded-md bg-pink-50">
            <h2 className="text-lg font-semibold text-pink-600">Processed Zoomed Video:</h2>
            <Divider className="bg-pink-300 my-2" />
            <video
              src={zoomedVideoUrl}
              controls
              className="w-full max-w-lg border border-gray-300 bg-black rounded-md"
            />
          </div>
        )} */}
      </div>
    </div>
  );
}
