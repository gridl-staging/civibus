<!-- [scrai:start] -->
## routes

| File | Summary |
| --- | --- |

| Directory | Summary |
| --- | --- |
| candidacy | — |
| candidate | The candidate directory provides server-side routing for candidate detail pages, handling slug collision resolution and canonical URL redirection. |
| candidates | — |
| committee | The committee directory handles dynamic routing for committee detail pages, using server-side logic to resolve committee IDs and canonicalize slugs for proper URL formatting. |
| committees | — |
| contest | — |
| office | — |
| officeholding | — |
| org | — |
| person | — |
| property | — |
| search | The search page server load function handles URL parameters for query string and entity type filtering, returning early with empty results if no query is provided, otherwise fetching results from the backend API. |
| sitemap.xml | This is a SvelteKit server endpoint that generates a dynamic XML sitemap by fetching paginated candidate and committee data from the API, building absolute URLs for static and dynamic routes, and returning properly formatted sitemap XML with XML-escaped content. |
<!-- [scrai:end] -->
