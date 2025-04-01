import streamlit as st
import boto3
import uuid
import os
import time
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables (for local development)
load_dotenv()

# App title and description
st.title("SmartFill : Automated Crisis Management Fill Form")
st.markdown("""
This application allows you to upload documents (PDF, TXT) for processing with the FAISS pipeline.
The documents will be analyzed using vector search and question-answering techniques.
""")

# Configure AWS clients - prioritize Streamlit secrets over environment variables
aws_region = st.secrets.get("AWS_REGION", os.getenv("AWS_REGION", "us-east-1"))
aws_access_key = st.secrets.get("AWS_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY_ID"))
aws_secret_key = st.secrets.get("AWS_SECRET_ACCESS_KEY", os.getenv("AWS_SECRET_ACCESS_KEY"))

# Set up AWS session with credentials from secrets
boto3.setup_default_session(
    region_name=aws_region,
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_key
)

s3_client = boto3.client('s3')
step_functions_client = boto3.client('stepfunctions')

# Bucket and Step Function information from secrets or environment variables
S3_BUCKET = st.secrets.get("S3_BUCKET", os.getenv("S3_BUCKET"))
STEP_FUNCTION_ARN = st.secrets.get("STEP_FUNCTION_ARN", os.getenv("STEP_FUNCTION_ARN"))

# Repurpose sidebar for app information and status
st.sidebar.header("Application Info")
st.sidebar.markdown("""
### SmartFill
*Automated Crisis Management Fill Form*

This application processes your uploaded documents to:
- Extract key information
- Answer structured questions
- Organize findings by topic

Processing is performed using:
- FAISS vector database
- Large language models
- AWS serverless infrastructure
""")

# Add session ID placeholder in sidebar - this will stay persistent
session_id_placeholder = st.sidebar.empty()

# Session management
if 'session_id' not in st.session_state:
    st.session_state.session_id = None
    
if 'last_check_time' not in st.session_state:
    st.session_state.last_check_time = time.time()
    
if 'auto_check' not in st.session_state:
    st.session_state.auto_check = False

# Generate a unique session ID
def generate_session_id():
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"{now}-{unique_id}"

# Automatic status checker function
def auto_check_status():
    if not st.session_state.execution_arn:
        return
        
    try:
        response = step_functions_client.describe_execution(
            executionArn=st.session_state.execution_arn
        )
        
        # Update session state
        current_status = response['status']
        st.session_state.execution_status = current_status
        
        # If execution is complete, stop auto-checking
        if current_status in ['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'ABORTED']:
            st.session_state.auto_check = False
            return current_status
            
        # Still running, keep checking
        return current_status
        
    except Exception as e:
        print(f"Error checking status: {str(e)}")
        st.session_state.auto_check = False
        return None

# File upload section
st.header("Upload Documents")
st.markdown("Upload PDF or TXT files for processing.")

# Add a text input area for direct text entry
st.subheader("Or Enter Text Directly")
user_text = st.text_area(
    "Enter text to be processed (will be saved as a .txt file)",
    height=200,
    placeholder="Describe your crisis here.",
    help="This text will be converted to a .txt file and processed alongside any uploaded files."
)

# Add file uploader below the text area
uploaded_files = st.file_uploader("Choose files (optional)", accept_multiple_files=True, type=["pdf", "txt"])

# Progress tracking
if 'uploaded_files' not in st.session_state:
    st.session_state.uploaded_files = []
    
if 'execution_arn' not in st.session_state:
    st.session_state.execution_arn = None
    
if 'execution_status' not in st.session_state:
    st.session_state.execution_status = None

# Display current session ID if available
if st.session_state.session_id:
    session_id_placeholder.markdown(f"**Current Session ID**: {st.session_state.session_id}")

# Automatically check status if enabled
if st.session_state.auto_check and st.session_state.execution_arn:
    # Display a spinner to indicate we're waiting for the process to complete
    with st.spinner('Waiting for processing to complete... This may take a few minutes.'):
        status = auto_check_status()
        
        # If status changed to a completion state, refresh UI
        if status in ['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'ABORTED']:
            st.rerun()
        else:
            # Still running, wait 2 seconds then reload
            time.sleep(2)
            st.rerun()

# Process files when the upload button is clicked
process_button = st.button("Process Content")
if (uploaded_files or user_text.strip()) and process_button:
    # Generate a new session ID for each processing job
    session_id = generate_session_id()
    st.session_state.session_id = session_id
    
    # Display the session ID in the sidebar
    session_id_placeholder.markdown(f"**Current Session ID**: {st.session_state.session_id}")
    
    file_paths = []
    
    # Create progress bar for uploads
    upload_progress = st.progress(0)
    upload_status = st.empty()
    
    # Set total files to upload (including user text if provided)
    total_files = len(uploaded_files) + (1 if user_text.strip() else 0)
    files_processed = 0
    
    # Process user-entered text if provided
    if user_text.strip():
        try:
            # Create a temporary file from the user's text
            text_filename = f"user_input_{int(time.time())}.txt"
            file_key = f"{session_id}/{text_filename}"
            
            # Upload the text as a file to S3
            upload_status.text(f"Uploading user-entered text as {text_filename}...")
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=file_key,
                Body=user_text.encode('utf-8')
            )
            
            # Add file path to the list
            file_paths.append(file_key)
            
            # Update progress
            files_processed += 1
            progress_pct = files_processed / total_files
            upload_progress.progress(progress_pct)
            
        except Exception as e:
            st.error(f"Error uploading user text: {str(e)}")
    
    # Process uploaded files
    for file in uploaded_files:
        try:
            # Create the S3 key with session_id prefix
            file_key = f"{session_id}/{file.name}"
            
            # Upload file to S3
            upload_status.text(f"Uploading {file.name}...")
            s3_client.upload_fileobj(file, S3_BUCKET, file_key)
            
            # Add file path to the list
            file_paths.append(file_key)
            
            # Update progress
            files_processed += 1
            progress_pct = files_processed / total_files
            upload_progress.progress(progress_pct)
            
        except Exception as e:
            st.error(f"Error uploading {file.name}: {str(e)}")
    
    if file_paths:
        upload_status.text("All content uploaded successfully!")
        st.session_state.uploaded_files = file_paths
        
        # Use a placeholder for the starting message so we can clear it later
        starting_msg = st.empty()
        starting_msg.info("Starting document processing pipeline...")
        
        # Start Step Function execution
        try:
            execution_input = {
                "session_id": session_id,
                "last_session_id": None
            }
            
            response = step_functions_client.start_execution(
                stateMachineArn=STEP_FUNCTION_ARN,
                name=f"Execution-{session_id}",
                input=json.dumps(execution_input)
            )
            
            st.session_state.execution_arn = response['executionArn']
            
            # Success message
            success_msg = st.empty()
            success_msg.success(f"Processing pipeline started successfully!")
            
            # Clear messages after a short delay
            time.sleep(1.5)
            upload_progress.empty()  # Clear the progress bar
            upload_status.empty()    # Clear the "All files uploaded successfully!" message
            starting_msg.empty()     # Clear the starting message
            success_msg.empty()      # Clear the success message
            
            # Enable automatic status checking
            st.session_state.auto_check = True
            
            # Start the automatic checking
            st.rerun()
            
        except Exception as e:
            starting_msg.empty()  # Clear the starting message
            st.error(f"Error starting Step Function: {str(e)}")
    else:
        st.error("No content was successfully uploaded. Please try again.")

# Display execution status and results
if st.session_state.execution_arn:
    status_container = st.container()
    
    with status_container:
        st.header("Execution Status")
        
        # Show current status
        if st.session_state.execution_status:
            st.write(f"Current Status: **{st.session_state.execution_status}**")
            
            if st.session_state.auto_check and st.session_state.execution_status == 'RUNNING':
                # Show an indication that we're automatically checking with a spinner
                with st.spinner('Processing your documents... This may take several minutes depending on file size and complexity.'):
                    st.info("The system is analyzing your documents. Please wait.")
            
            # Only show the appropriate message for the current status
            if st.session_state.execution_status == 'SUCCEEDED':
                st.success("Processing completed successfully!")
                time.sleep(1)
                
                # Try to parse and display the output
                try:
                    response = step_functions_client.describe_execution(
                        executionArn=st.session_state.execution_arn
                    )
                    
                    output = json.loads(response.get('output', '{}'))
                    
                    # Extract and display only the topics_results
                    if 'topic_results' in output and 'topics' in output:
                        st.header("Processing Results")
                        
                        # Get the topics list and topics_data
                        topics = output['topics']
                        topics_data = output['topic_results']
                        
                        # Make sure we have the same number of topics and topic_data entries
                        if len(topics) == len(topics_data):
                            for topic_idx, (topic_name, topic_data) in enumerate(zip(topics, topics_data)):
                                st.subheader(f"{topic_name}")
                                
                                # Extract all questions and sort by question_id
                                questions = []
                                for item in topic_data:
                                    if 'body' in item:
                                        body = item['body']
                                        
                                        # Extract the main fields from body
                                        if isinstance(body, dict):
                                            questions.append(body)
                                
                                # Sort questions by question_id
                                sorted_questions = sorted(questions, key=lambda q: int(q.get('question_id', '0')))
                                
                                # Display the sorted questions
                                for body in sorted_questions:
                                    question_id = body.get('question_id', 'N/A')
                                    question = body.get('question', 'N/A')
                                    answer = body.get('answer', 'N/A')
                                    
                                    # Display the main question and answer
                                    st.markdown(f"**Question {question_id}**: {question}")
                                    st.markdown(f"**Answer**: {answer}")
                                    
                                    # Process follow-up questions if present
                                    follow_up = body.get('follow-up', [])
                                    if follow_up and len(follow_up) > 0:
                                        st.markdown("**Follow-up Questions:**")
                                        
                                        for idx, fu_item in enumerate(follow_up):
                                            fu_question = fu_item.get('question', 'N/A').get('S', 'N/A')
                                            fu_answer = fu_item.get('answer', 'N/A')
                                            
                                            st.markdown(f"**{idx+1}. {fu_question}**")
                                            st.markdown(f"   Answer: {fu_answer}")
                                    
                                    st.markdown("---")  # Add a separator between questions
                        else:
                            st.warning("Topic names and data lengths don't match. Displaying data without topic names.")
                            # Fallback to the previous display logic
                            for topic_idx, topic_data in enumerate(topics_data):
                                st.subheader(f"Topic {topic_idx + 1}")
                                
                                # Process each item in the topic data
                                for item in topic_data:
                                    if 'body' in item:
                                        body = item['body']
                                        
                                        # Extract the main fields from body
                                        if isinstance(body, dict):
                                            question_id = body.get('question_id', 'N/A')
                                            question = body.get('question', 'N/A')
                                            answer = body.get('answer', 'N/A')
                                            
                                            # Display the main question and answer
                                            st.markdown(f"**Question {question_id}**: {question}")
                                            st.markdown(f"**Answer**: {answer}")
                                            
                                            # Process follow-up questions if present
                                            follow_up = body.get('follow-up', [])
                                            if follow_up and len(follow_up) > 0:
                                                st.markdown("**Follow-up Questions:**")
                                                
                                                for idx, fu_item in enumerate(follow_up):
                                                    fu_question = fu_item.get('question', 'N/A').get('S', 'N/A')
                                                    fu_answer = fu_item.get('answer', 'N/A')
                                                    
                                                    st.markdown(f"**{idx+1}. {fu_question}**")
                                                    st.markdown(f"   Answer: {fu_answer}")
                                            
                                            st.markdown("---")  # Add a separator between questions
                    elif 'topic_results' in output:
                        # If only topic_results are available but no topics list
                        st.header("Processing Results")
                        topics_data = output['topic_results']
                        
                        for topic_idx, topic_data in enumerate(topics_data):
                            st.subheader(f"Topic {topic_idx + 1}")
                            
                            # Process each item in the topic data
                            for item in topic_data:
                                if 'body' in item:
                                    body = item['body']
                                    
                                    # Extract the main fields from body
                                    if isinstance(body, dict):
                                        question_id = body.get('question_id', 'N/A')
                                        question = body.get('question', 'N/A')
                                        answer = body.get('answer', 'N/A')
                                        
                                        # Display the main question and answer
                                        st.markdown(f"**Question {question_id}**: {question}")
                                        st.markdown(f"**Answer**: {answer}")
                                        
                                        # Process follow-up questions if present
                                        follow_up = body.get('follow-up', [])
                                        if follow_up and len(follow_up) > 0:
                                            st.markdown("**Follow-up Questions:**")
                                            
                                            for idx, fu_item in enumerate(follow_up):
                                                fu_question = fu_item.get('question', 'N/A').get('S', 'N/A')
                                                fu_answer = fu_item.get('answer', 'N/A')
                                                
                                                st.markdown(f"**{idx+1}. {fu_question}**")
                                                st.markdown(f"   Answer: {fu_answer}")
                                        
                                        st.markdown("---")  # Add a separator between questions
                except Exception as e:
                    st.warning(f"Could not parse execution output: {str(e)}")
                
            elif st.session_state.execution_status == 'FAILED':
                st.error("Processing failed.")
                
                # Try to parse and display the error
                try:
                    response = step_functions_client.describe_execution(
                        executionArn=st.session_state.execution_arn
                    )
                    error = json.loads(response.get('error', '{}'))
                    cause = json.loads(response.get('cause', '{}'))
                    st.error(f"Error: {error}")
                    st.error(f"Cause: {cause}")
                except Exception as e:
                    st.warning(f"Could not parse error details: {str(e)}")
                
            elif st.session_state.execution_status == 'RUNNING':
                if not st.session_state.auto_check:
                    st.info("Processing is running.")
                    
                    # Offer manual check button as fallback
                    if st.button("Check Status Manually"):
                        auto_check_status()
                        st.rerun()
        else:
            # Initial state - automatic checking will take over
            st.info("Awaiting status update...")
            
            # Start checking if auto-check is enabled
            if st.session_state.auto_check:
                st.rerun()

