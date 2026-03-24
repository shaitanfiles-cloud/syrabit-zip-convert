import { Helmet } from "react-helmet-async";

export default function PageMeta({
  title,
  description,
  url,
  image = "/og-default.png"
}) {
  const siteName = "Syrabit.ai";

  return (
    <Helmet
      title={title}
      titleTemplate={`%s | ${siteName}`}
      defaultTitle={siteName}
    >
      <meta name="description" content={description} />

      <link rel="canonical" href={url} />

      {/* OpenGraph */}
      <meta property="og:title" content={title} />
      <meta property="og:description" content={description} />
      <meta property="og:type" content="website" />
      <meta property="og:url" content={url} />
      <meta property="og:image" content={image} />

      {/* Twitter */}
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={title} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content={image} />
    </Helmet>
  );
}
